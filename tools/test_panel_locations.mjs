#!/usr/bin/env node
/* Synthetic location UI contracts. Node standard library only; runs real panel.js. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../jobs/panel_assets/panel.js',import.meta.url),'utf8');
const tick=()=>new Promise(r=>setTimeout(r,0));
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
class El{
  constructor(tag='div',dataset={}){
    this.tagName=tag.toUpperCase();this.dataset=dataset;this.value='';this.defaultValue='';this.hidden=false;
    this.disabled=false;this.textContent='';this.q={};this.classes=new Set();this.attrs={};this._html='';
    this.classList={contains:k=>this.classes.has(k),add:(...ks)=>ks.forEach(k=>this.classes.add(k)),
      remove:(...ks)=>ks.forEach(k=>this.classes.delete(k)),toggle:(k,v)=>{v=v??!this.classes.has(k);v?this.classes.add(k):this.classes.delete(k);return v;}};
  }
  set className(v){this.classes=new Set(v.split(/\s+/));}get className(){return [...this.classes].join(' ');}
  set innerHTML(v){this._html=v;if(this.render)this.render(v);}get innerHTML(){return this._html;}
  querySelectorAll(s){return this.q[s]||[];}querySelector(s){return this.querySelectorAll(s)[0]||null;}
  closest(s){if(s==='[data-location-id]')return this.dataset.locationId!==undefined?this:this.host||null;
    if(s==='.location-panel')return this.locationPanel||null;return null;}
  setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}
  focus(){this.focused=true;}addEventListener(){}removeEventListener(){}appendChild(){}
}
function setup(){
  const ids=new Map(),reg={},body=new El('body');
  const document={body,activeElement:body,hidden:false,documentElement:{lang:'en'},
    getElementById:k=>ids.get(k)||null,querySelectorAll:s=>reg[s]||[],querySelector:s=>(reg[s]||[])[0]||null,
    addEventListener(){},createElement:t=>new El(t)};
  const sandbox={document,console,URL,URLSearchParams,Map,Set,WeakMap,Promise,Date,JSON,Number,
    setTimeout,clearTimeout,requestAnimationFrame:f=>f(),addEventListener(){},
    matchMedia:()=>({matches:true,addEventListener(){}}),
    localStorage:{getItem(){return null;},setItem(){}},sessionStorage:{getItem(){return null;},setItem(){}},
    location:{href:'http://localhost/?view=all&geo=Melbourne+VIC&mode=hybrid',pathname:'/',search:'?view=all&geo=Melbourne+VIC&mode=hybrid',hash:''},
    __LABELS__:{A:{action:'applied',note:'Legacy；'}},__VIEW__:'all',confirm:()=>false};
  sandbox.window=sandbox;
  sandbox.history={replaceState(_a,_b,url){const u=new URL(url,sandbox.location.href);Object.assign(sandbox.location,{href:u.href,hash:u.hash,search:u.search});}};
  const pane=new El();ids.set('detail',pane);ids.set('toast',new El());
  let scope;
  function mount(id='L1',uid='A'){
    scope=new El('div',{uid,locationId:id,scopeLabel:JSON.stringify({action:null,note:null})});
    reg['#detail [data-location-scope]']=[scope];reg['#detail [data-uid="'+uid+'"]']=[scope];
    const raw=new El('input');raw.value=raw.defaultValue='Melbourne VIC';raw.host=scope;
    const mode=new El('select',{loaded:'hybrid'});mode.value='hybrid';mode.host=scope;
    ids.set('location-raw',raw);ids.set('location-mode',mode);ids.set('location-status',new El());
    const select=new El('select');select.value=id;ids.set('location-choice',select);
    scope.q['.location-editor input,.location-editor select,.location-editor button']=[raw,mode];
    return scope;
  }
  pane.render=html=>{if(html.startsWith('DETAIL:'))mount(html.slice(7));};
  const calls=[];
  let route=async(url,body)=>({ok:true,json:async()=>url.startsWith('/api/job')
    ?{html:'DETAIL:'+(new URL(url,'http://localhost').searchParams.get('location_id')??'L2')}
    :{ok:true,field:body?.field,value:body?.value,location_id:body?.location_id}});
  sandbox.fetch=async(url,opts)=>{const body=opts?.body?JSON.parse(opts.body):null;calls.push({url:String(url),body});return route(String(url),body);};
  vm.createContext(sandbox);
  vm.runInContext(source+`\n;globalThis.api={openJob,setNote,noteAdopt,setLabel,changeLocation,saveLocation,allowDetailNavigation,
    refreshDot,scopeLabel,detailHash,readDetailHash,viewParams,geoTyping,geoKeys,applyGeo,filterDraftBegin,filterDraftDiscard,
    filterDraftCount,navKeyIgnored,imeStart,imeEnd,resetControl,hasDetailDraft,focusLocationChoice,
    current(uid,id){OPEN_UID=uid;OPEN_LOCATION=id;},pending(){return LABEL_WRITES.size;}};`,sandbox);
  return {api:sandbox.api,sandbox,document,ids,reg,pane,calls,mount,setRoute:f=>{route=f;}};
}
let passed=0;
async function test(name,fn){await fn();passed++;console.log('[PASS]',name);}
await test('detail default is chosen by backend; filters travel; explicit legacy and UID hashes survive',async()=>{
  const t=setup();await t.api.openJob('A');
  const first=new URL(t.calls[0].url,'http://localhost');
  assert.equal(first.searchParams.has('location_id'),false);assert.equal(first.searchParams.get('geo'),'Melbourne VIC');
  assert.equal(first.searchParams.get('mode'),'hybrid');assert.equal(t.sandbox.location.hash,'#A&location_id=L2');
  await t.api.openJob('A','');assert.equal(new URL(t.calls.at(-1).url,'http://localhost').searchParams.get('location_id'),'');
  const hash=t.api.detailHash('seek:A & B','L&2');t.sandbox.location.hash=hash;
  assert.deepEqual(JSON.parse(JSON.stringify(t.api.readDetailHash())),{uid:'seek:A & B',id:'L&2'});
  t.sandbox.location.hash='#seek%3Aold';assert.equal(t.api.readDetailHash().uid,'seek:old');assert.equal(t.api.readDetailHash().id,undefined);
  await t.api.openJob('B');assert.equal(new URL(t.calls.at(-1).url,'http://localhost').searchParams.has('location_id'),false);
});
await test('queued notes capture scope and preserve legacy and newer drafts',async()=>{
  const t=setup(),old=t.mount(),input=new El('input',{uid:'A'});input.host=old;t.api.noteAdopt(input,'');
  const first=deferred();let n=0;t.setRoute(async(_url,b)=>{if(++n===1)return first.promise;return {ok:true,json:async()=>({value:b.value+'；',location_id:b.location_id})};});
  input.value='first';const p1=t.api.setNote(input);input.value='second';const p2=t.api.setNote(input);
  t.mount('L2');input.value='unsaved third';
  first.resolve({ok:true,json:async()=>({value:'first；',location_id:'L1'})});await Promise.all([p1,p2]);
  assert.equal(t.calls.length,2);assert.deepEqual(t.calls.map(c=>c.body.location_id),['L1','L1']);
  assert.equal(input.value,'unsaved third');assert.equal(t.api.scopeLabel('A','L1').note,'second；');
  assert.equal(t.api.scopeLabel('A','L2').note,undefined);assert.equal(t.api.scopeLabel('A','').note,'Legacy；');
});
await test('late action response updates matching card only and leaves other scope and legacy untouched',async()=>{
  const t=setup(),scope=t.mount(),button=new El('button',{uid:'A',field:'action',value:'saved'});button.host=scope;
  const nodes=['L1','L2',''].map(id=>{const host=new El('div',{locationId:id});const dot=new El();dot.host=host;dot.textContent='unchanged';return dot;});
  t.reg['.prog[data-prog-uid="A"]']=nodes;
  t.reg['[data-uid="A"][data-field]']=[button];const reply=deferred();t.setRoute(()=>reply.promise);
  const saving=t.api.setLabel('A','action','saved',button);assert.equal(button.disabled,true);t.mount('L2');
  reply.resolve({ok:true,json:async()=>({value:'saved',location_id:'L1',label:{action:'saved'}})});await saving;
  assert.equal(t.calls[0].body.location_id,'L1');assert.equal(nodes[0].textContent,'value.action.saved');
  assert.equal(nodes[1].textContent,'unchanged');assert.equal(nodes[2].textContent,'unchanged');
  assert.equal(t.api.scopeLabel('A','').action,'applied');assert.equal(button.disabled,false);
});
await test('wrong scope response is rejected and a failed action blocks location switch',async()=>{
  const t=setup(),scope=t.mount(),button=new El('button',{uid:'A',field:'action',value:'saved'});button.host=scope;
  t.api.current('A','L1');const response=deferred();t.setRoute(()=>response.promise);
  const saving=t.api.setLabel('A','action','saved',button),choice=t.ids.get('location-choice');choice.value='L2';
  const changing=t.api.changeLocation(choice);response.resolve({ok:true,json:async()=>({value:'saved',location_id:'WRONG'})});
  await Promise.all([saving,changing]);assert.equal(choice.value,'L1');assert.equal(t.calls.length,1);
  assert.equal(t.api.scopeLabel('A','L1').action,undefined);
});
await test('dirty note and correction gate same-UID scope switching; failed note is retryable',async()=>{
  const t=setup(),scope=t.mount();t.api.current('A','L1');const input=new El('input',{uid:'A'});input.host=scope;t.api.noteAdopt(input,'');input.value='keep me';
  t.reg['.note input']=[input];t.setRoute(async()=>({ok:false,text:async()=>'{"error":"write_failed"}'}));
  await t.api.setNote(input);assert.equal(input.value,'keep me');assert.equal(input.dataset.noteLoaded,'');
  const choice=t.ids.get('location-choice');choice.value='L2';await t.api.changeLocation(choice);assert.equal(t.calls.length,1);
  t.reg['.note input']=[];const raw=t.ids.get('location-raw');raw.value='Sydney NSW';choice.value='L2';
  await t.api.changeLocation(choice);assert.equal(t.calls.length,1);assert.equal(choice.value,'L1');
});
await test('location save failure keeps input; retry captures id, reloads safely and reports list refresh',async()=>{
  const t=setup();t.mount();t.api.current('A','L1');const raw=t.ids.get('location-raw');raw.value='Richmond VIC';
  t.setRoute(async()=>({ok:false,text:async()=>'{"error":"write_failed"}'}));await t.api.saveLocation(false);
  assert.equal(raw.value,'Richmond VIC');assert.equal(raw.disabled,false);assert.equal(t.ids.get('location-status').textContent,'location.failed');
  t.setRoute(async(url,b)=>({ok:true,json:async()=>url.startsWith('/api/job')?{html:'DETAIL:L1'}:{ok:true,location_id:b.location_id}}));
  await t.api.saveLocation(false);assert.equal(t.calls[1].body.raw,'Richmond VIC');assert.equal(t.calls[1].body.location_id,'L1');
  assert.equal(t.calls.at(-1).url.startsWith('/api/job?'),true);assert.equal(t.ids.get('toast').textContent,'location.saved');
  await t.api.saveLocation(true);assert.equal(t.calls.at(-2).body.raw,null);
});
await test('navigation while correction saves retains destination and never reloads old scope',async()=>{
  const t=setup();t.mount();t.api.current('A','L1');t.ids.get('location-raw').value='Richmond VIC';
  const reply=deferred();t.setRoute(async(url)=>url==='/api/location'?reply.promise:{ok:true,json:async()=>({html:'DETAIL:L2'})});
  const saving=t.api.saveLocation(false),changing=t.api.openJob('B');await tick();assert.equal(t.calls.length,1);
  reply.resolve({ok:true,json:async()=>({ok:true,location_id:'L1'})});await Promise.all([saving,changing]);
  assert.equal(t.calls.length,2);assert.equal(new URL(t.calls[1].url,'http://localhost').searchParams.get('uid'),'B');
});
await test('geo typing is explicit, Enter and IME work, unrelated mode changes keep applied geo',async()=>{
  const t=setup(),geo=new El('input',{fkey:'geo'}),mode=new El('select',{fkey:'mode'});
  geo.value=geo.defaultValue='VIC';mode.value='hybrid';t.reg['[data-fkey]']=[geo,mode];t.reg['[data-fkey="geo"]']=[geo];
  geo.value='Melbourne VIC';t.api.geoTyping();assert.equal(t.api.viewParams().get('geo'),'VIC');assert.equal(t.calls.length,0);
  let prevented=0;t.api.imeStart(geo);t.api.geoKeys({key:'Enter',target:geo,preventDefault(){prevented++;}});assert.equal(prevented,0);
  t.api.imeEnd(geo);t.api.geoKeys({key:'Enter',target:geo,preventDefault(){prevented++;}});assert.equal(prevented,0);
  await new Promise(r=>setTimeout(r,125));t.api.geoKeys({key:'Enter',target:geo,preventDefault(){prevented++;}});await tick();
  assert.equal(prevented,1);assert.equal(t.api.viewParams().get('geo'),'Melbourne VIC');
  t.reg['[data-fkey="geo"]']=[geo];t.api.resetControl('geo');assert.equal(t.api.viewParams().has('geo'),false);
  mode.value='any';assert.equal(t.api.viewParams().has('mode'),false);
});
await test('mobile geo draft applies/discards with original filter state and location controls own J/K',async()=>{
  const t=setup(),geo=new El('input',{fkey:'geo'}),more=new El();geo.defaultValue=geo.value='VIC';
  t.reg['[data-fkey]']=[geo];t.ids.set('more-panel',more);t.document.body.classList.add('portrait');
  t.api.filterDraftBegin();geo.value='3000';t.api.geoTyping();assert.equal(t.api.filterDraftCount(),1);
  assert.equal(t.api.viewParams().get('geo'),'3000');t.api.filterDraftDiscard();assert.equal(geo.value,'VIC');
  const button=new El('button');button.locationPanel=new El();assert.equal(t.api.navKeyIgnored({target:button}),true);
  for(const tag of ['input','select'])assert.equal(t.api.navKeyIgnored({target:new El(tag)}),true);
});
await test('record-scope chip returns to the selector, closing the phone record drawer without losing a draft',async()=>{
  const t=setup();t.mount('L1');const select=t.ids.get('location-choice'),sheet=new El();let scrolled=null;
  select.scrollIntoView=o=>{scrolled=o;};sheet.contains=()=>false;t.ids.set('label-sheet',sheet);
  t.ids.get('location-raw').value='Melbourne VIC 3000';
  t.pane.classes.add('label-open');t.api.focusLocationChoice();
  assert.equal(t.pane.classList.contains('label-open'),false);assert.equal(select.focused,true);
  assert.equal(scrolled.block,'center');assert.equal(t.api.hasDetailDraft(),true);
  assert.equal(t.calls.length,0);
  t.ids.delete('location-choice');t.api.focusLocationChoice();assert.equal(t.calls.length,0);
});
console.log(`${passed} location behavior scenarios passed`);
