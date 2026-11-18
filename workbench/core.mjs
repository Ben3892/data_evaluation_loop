export const escapeHtml = v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function parseRows(text){
 const t=text.trim(); if(!t)throw Error('输入为空');
 if(t.startsWith('[')){const a=JSON.parse(t);if(!Array.isArray(a))throw Error('需要数组');return a;}
 return t.split(/\r?\n/).filter(x=>x.trim()).map((s,i)=>{try{return JSON.parse(s);}catch(e){throw Error(`第 ${i+1} 行 JSON 解析失败：${e.message}`);}});
}
const supported=new Set(['$schema','$id','$ref','title','description','type','required','properties','additionalProperties','items','enum','const','minimum','maximum','minLength','maxLength','pattern','minItems','maxItems','uniqueItems','anyOf','oneOf','allOf','definitions','$defs','default','examples']);
export function schemaCheck(value,schema){
 const errors=[]; const root=schema;
 function check(v,s,p,stack=0){
  if(stack>60)throw Error('schema 递归深度超过限制');
  if(s===true)return;if(s===false){errors.push(`${p}: schema=false`);return;}
  if(!s||typeof s!=='object'||Array.isArray(s))throw Error('无效 Schema 对象');
  for(const k of Object.keys(s))if(!supported.has(k))throw Error(`浏览器校验暂不支持 ${k}；请使用下载包中的 Python jsonschema 完整校验`);
  if(s.$ref){if(!s.$ref.startsWith('#/'))throw Error('浏览器不解析外部 $ref');let ref=root;for(const k of s.$ref.slice(2).split('/'))ref=ref?.[k.replace(/~1/g,'/').replace(/~0/g,'~')];if(!ref)throw Error('无法解析 '+s.$ref);check(v,ref,p,stack+1);return;}
  const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  if('const'in s&&!eq(v,s.const))errors.push(`${p}: const 应为 ${JSON.stringify(s.const)}`);
  if(s.enum&&!s.enum.some(x=>eq(x,v)))errors.push(`${p}: 不在 enum 范围`);
  const type=t=>t==='null'?v===null:t==='array'?Array.isArray(v):t==='object'?v!==null&&typeof v==='object'&&!Array.isArray(v):t==='integer'?typeof v==='number'&&Number.isInteger(v):t==='number'?typeof v==='number'&&Number.isFinite(v):typeof v===t;
  if(s.type&&!(Array.isArray(s.type)?s.type:[s.type]).some(type)){errors.push(`${p}: type 应为 ${s.type}`);return;}
  for(const keyword of ['anyOf','oneOf','allOf'])if(s[keyword]){const statuses=s[keyword].map(sub=>{const start=errors.length;check(v,sub,p,stack+1);const ok=errors.length===start;errors.splice(start);return ok;});if(keyword==='anyOf'&&!statuses.some(Boolean)||keyword==='oneOf'&&statuses.filter(Boolean).length!==1||keyword==='allOf'&&!statuses.every(Boolean))errors.push(`${p}: ${keyword} 校验失败`);}
  if(v!==null&&typeof v==='object'&&!Array.isArray(v)){
   for(const key of s.required||[])if(!(key in v))errors.push(`${p}/${key}: 缺少必填字段`);
   for(const key of Object.keys(v)){if(s.properties&&key in s.properties)check(v[key],s.properties[key],`${p}/${key}`,stack+1);else if(s.additionalProperties===false)errors.push(`${p}/${key}: 不允许额外字段`);else if(s.additionalProperties&&typeof s.additionalProperties==='object')check(v[key],s.additionalProperties,`${p}/${key}`,stack+1);}
  }
  if(Array.isArray(v)){
   if(s.minItems!=null&&v.length<s.minItems)errors.push(`${p}: minItems`);if(s.maxItems!=null&&v.length>s.maxItems)errors.push(`${p}: maxItems`);
   if(s.uniqueItems&&new Set(v.map(x=>JSON.stringify(x))).size!==v.length)errors.push(`${p}: uniqueItems`);
   if(s.items)v.forEach((x,i)=>check(x,s.items,`${p}/${i}`,stack+1));
  }
  if(typeof v==='number'){if(s.minimum!=null&&v<s.minimum)errors.push(`${p}: minimum ${s.minimum}`);if(s.maximum!=null&&v>s.maximum)errors.push(`${p}: maximum ${s.maximum}`);}
  if(typeof v==='string'){if(s.minLength!=null&&[...v].length<s.minLength)errors.push(`${p}: minLength ${s.minLength}`);if(s.maxLength!=null&&[...v].length>s.maxLength)errors.push(`${p}: maxLength ${s.maxLength}`);if(s.pattern&&!new RegExp(s.pattern).test(v))errors.push(`${p}: pattern`);}
 }
 check(value,schema,'$');return errors;
}
export function validateResult(r,schema){
 const errors=schemaCheck(r,schema);if(errors.length)throw Error(errors.join('\n'));
 const ids=r.steps.map(s=>s.step_id);if(new Set(ids).size!==ids.length||ids.some((x,i)=>i&&x<ids[i-1]))throw Error('step_ids_must_be_unique_and_ordered');
 const bad=r.steps.filter(s=>s.validity==='incorrect');for(const s of bad)if(!s.error_type||!s.evidence.trim())throw Error('incorrect_step_requires_type_and_evidence');
 const error=s=>s?{step_id:s.step_id,type:s.error_type,evidence:s.evidence}:null;
 const equal=(a,b)=>a===null&&b===null||a&&b&&a.step_id===b.step_id&&a.type===b.type&&a.evidence===b.evidence;
 if(!equal(r.first_error,error(bad[0])))throw Error('first_error_must_match_earliest_annotated_incorrect_step');
 if(r.primary_error&&!bad.some(s=>equal(r.primary_error,error(s))))throw Error('primary_error_must_reference_an_annotated_incorrect_step');
 if(r.annotation_status==='unreviewed'&&(bad.length||r.primary_error))throw Error('unreviewed_cannot_contain_error_assertions');return r;
}
export function evaluate(r,schema,taskId='atomic_exact.v1'){
 if(typeof r.answer!=='string'||typeof r.reference!=='string')throw Error('answer/reference 必须为字符串');
 const bad=(r.steps||[]).filter(s=>s.validity==='incorrect');
 const v={schema_version:'1.0',run_id:r.run_id,sample_id:r.sample_id,attempt_id:r.attempt_id,task_id:taskId,model:r.model,protocol:r.protocol,answer:r.answer,reference:r.reference,correct:r.answer.trim()===r.reference.trim(),annotation_status:r.annotation_status||'unreviewed',steps:r.steps||[],first_error:bad.length?{step_id:bad[0].step_id,type:bad[0].error_type,evidence:bad[0].evidence}:null,primary_error:r.primary_error||null};return validateResult(v,schema);
}
export function summarize(rows,baseline='base',target='candidate'){
 if(baseline===target)throw Error('baseline_and_target_must_differ');
 const seen=new Set(),groups=new Map(),a=new Map(),b=new Map();
 for(const r of rows){const key=JSON.stringify([r.run_id,r.task_id,r.sample_id,r.attempt_id,r.protocol]);if(seen.has(key))throw Error('duplicate_result_key: '+key);seen.add(key);
 const q=JSON.stringify([r.run_id,r.task_id,r.sample_id,r.protocol]);if(!groups.has(q))groups.set(q,{run_id:r.run_id,task_id:r.task_id,sample_id:r.sample_id,protocol:r.protocol,n:0,correct:0});const g=groups.get(q);g.n++;g.correct+=Number(r.correct);
 const pairKey=JSON.stringify([r.task_id,r.sample_id,r.attempt_id,r.protocol]);if(r.run_id===baseline)a.set(pairKey,r);if(r.run_id===target)b.set(pairKey,r);
 }
 const transitions={'correct→correct':0,'correct→incorrect':0,'incorrect→correct':0,'incorrect→incorrect':0};let paired=0,unmatched=0;
 for(const [key,r]of a){if(!b.has(key)){unmatched++;continue;}const t=b.get(key);if(r.reference!==t.reference)throw Error('paired_reference_mismatch: '+key);transitions[`${r.correct?'correct':'incorrect'}→${t.correct?'correct':'incorrect'}`]++;paired++;}
 for(const key of b.keys())if(!a.has(key))unmatched++;
 const first_error_types={};for(const r of rows)if(r.first_error)first_error_types[r.first_error.type]=(first_error_types[r.first_error.type]||0)+1;
 return {records:rows.length,per_question:[...groups.values()].map(g=>({...g,accuracy:g.correct/g.n})),transitions,paired,unmatched,first_error_types};
}
