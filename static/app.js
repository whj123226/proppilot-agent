"use strict";
const $=id=>document.getElementById(id);
let activeTask=null, busy=false;
const labels={waiting_input:"需要补充信息",waiting_confirmation:"请核对并确认",success:"工单已创建",cancelled:"办理已取消",failed:"办理未完成",conflict:"当前状态不允许此操作",not_found:"任务不存在",not_started:"尚未开始"};
async function api(path,body){const opts={credentials:"same-origin",headers:{}};if(body!==undefined){opts.method="POST";opts.headers["Content-Type"]="application/json";opts.body=JSON.stringify(body);}const response=await fetch(path,opts);const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"输入格式不正确或服务暂不可用");return data;}
async function run(fn){if(busy)return;busy=true;$("error").textContent="";document.querySelectorAll("button").forEach(b=>b.disabled=true);try{await fn();}catch(e){$("error").textContent=e.message;}finally{busy=false;document.querySelectorAll("button").forEach(b=>b.disabled=false);}}
function showTask(data){activeTask=data.task_id;$("task-card").hidden=false;$("task-status").textContent=labels[data.status]||data.status;$("task-message").textContent=data.message;$("task-number").textContent="任务编号："+activeTask;const fields=$("fields");fields.replaceChildren();const names={room_id:"房间",location:"位置",description:"故障",missing_fields:"缺失信息",order_id:"工单编号"};for(const [key,label]of Object.entries(names)){const value=data.data?.[key];if(value!==undefined&&value!==null&&value!==""&&!(Array.isArray(value)&&value.length===0)){const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=label;dd.textContent=Array.isArray(value)?value.join("、"):value;fields.append(dt,dd);}}const actions=data.data?.available_actions||[];$("supplement-box").hidden=!actions.includes("supplement");for(const action of["confirm","cancel","retry"])$(action).hidden=!actions.includes(action);}
async function refresh(){const [tasks,orders]=await Promise.all([api("/api/tasks"),api("/api/orders")]);$("tasks").replaceChildren();for(const task of tasks.tasks){const row=document.createElement("div"),text=document.createElement("div"),btn=document.createElement("button");row.className="record";text.className="mono";text.textContent=task.task_id;btn.textContent="查看 / 继续";btn.onclick=()=>run(async()=>{switchTab("repair");showTask(await api("/api/tasks/"+task.task_id));});row.append(text,btn);$("tasks").append(row);}if(!tasks.tasks.length)$("tasks").textContent="暂无任务";$("orders").replaceChildren();for(const order of orders.orders){const row=document.createElement("div");row.className="record";const line=document.createElement("div"),num=document.createElement("div");line.textContent=order.room_id+" · "+order.status+" · "+order.description;num.className="mono";num.textContent=order.order_id;row.append(line,num);$("orders").append(row);}if(!orders.orders.length)$("orders").textContent="暂无工单";}
function switchTab(name){document.querySelectorAll(".tab").forEach(el=>el.hidden=el.id!==name);document.querySelectorAll("[data-tab]").forEach(el=>el.classList.toggle("selected",el.dataset.tab===name));}
document.querySelectorAll("[data-tab]").forEach(btn=>btn.onclick=()=>switchTab(btn.dataset.tab));
$("start").onclick=()=>run(async()=>{showTask(await api("/api/tasks",{text:$("repair-text").value}));await refresh();});
$("supplement").onclick=()=>run(async()=>{showTask(await api(`/api/tasks/${activeTask}/supplement`,{text:$("supplement-text").value}));$("supplement-text").value="";await refresh();});
for(const action of["confirm","cancel","retry"])$(action).onclick=()=>run(async()=>{showTask(await api(`/api/tasks/${activeTask}/${action}`,{}));await refresh();});
$("refresh").onclick=()=>run(refresh);
$("ask").onclick=()=>run(async()=>{const data=await api("/api/consult",{text:$("question").value});$("answer").textContent=data.answer;$("sources").replaceChildren();for(const src of data.sources||[]){const el=document.createElement("div");el.className="source";el.textContent=`[${src.id}] ${src.title}\n${src.content}`;$("sources").append(el);}});
$("fee-query").onclick=()=>run(async()=>{const result=await api("/api/fees",{room_id:$("room").value});$("fee-result").textContent=`${result.data.room_id} 演示欠费：¥${result.data.amount.toFixed(2)}`;});
// 修改表单独立于“新建报修描述”，始终操作当前task_id。
const editButton=document.createElement("button");
editButton.textContent="修改报修信息";
editButton.hidden=true;
$("actions").prepend(editButton);
const editForm=document.createElement("form");
editForm.hidden=true;
const editInputs={};
for(const [key,label,max] of [["room_id","房间编号",4],["location","故障位置",100],["description","故障描述",1000]]){
  const caption=document.createElement("label"),input=document.createElement("input");
  input.id="edit-"+key;input.required=true;input.maxLength=max;
  caption.htmlFor=input.id;caption.textContent=label;
  editInputs[key]=input;editForm.append(caption,input);
}
const saveEdit=document.createElement("button"),closeEdit=document.createElement("button");
saveEdit.type="submit";saveEdit.className="primary";saveEdit.textContent="保存修改，重新核对";
closeEdit.type="button";closeEdit.textContent="放弃本次修改";
editForm.append(saveEdit,closeEdit);$("actions").before(editForm);
function closeEditor(){editForm.hidden=true;$("actions").hidden=false;}
editButton.onclick=()=>{editForm.hidden=false;$("actions").hidden=true;editInputs.room_id.focus();};
closeEdit.onclick=closeEditor;
const renderTask=showTask;
showTask=function(data){
  renderTask(data);closeEditor();
  editButton.hidden=!(data.data?.available_actions||[]).includes("edit");
  for(const key of Object.keys(editInputs))editInputs[key].value=data.data?.[key]||"";
};
editForm.onsubmit=event=>{
  event.preventDefault();
  run(async()=>{
    const fields=Object.fromEntries(Object.entries(editInputs).map(([key,input])=>[key,input.value.trim()]));
    fields.room_id=fields.room_id.toUpperCase();
    const result=await api(`/api/tasks/${activeTask}/edit`,fields);
    if(result.status==="invalid_input"||result.status==="conflict")throw Error(result.message);
    showTask(result);await refresh();
  });
};
run(async()=>{const info=await api("/api/session");$("notice").textContent=info.notice+` 每位访客每天最多${info.daily_limit}次操作。`;await refresh();});
