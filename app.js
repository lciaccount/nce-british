/* One persistent media element for Safari; all text comes from the local corpus. */
(() => {
'use strict';
const $=s=>document.querySelector(s), data=NCE_DATA.lessons, KEY='nce-study-v1';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let saved;try{saved=JSON.parse(localStorage.getItem(KEY)||'{}');}catch{saved={};}saved=saved&&typeof saved==='object'?saved:{};
const validIds=new Set(data.flatMap(l=>l.cues.map(c=>c.id)));
const prefs={speed:1,gap:.5,repeat:0,font:100,hide:false,details:false,theme:'light',intro:false,...saved};
prefs.speed=Number.isFinite(+prefs.speed)&&+prefs.speed>=.5&&+prefs.speed<=2?+prefs.speed:1;
prefs.font=Number.isFinite(+prefs.font)&&+prefs.font>=80&&+prefs.font<=160?+prefs.font:100;
const favorites=new Set((Array.isArray(saved.favorites)?saved.favorites:[]).filter(id=>validIds.has(id)));
const mastered=new Set((Array.isArray(saved.mastered)?saved.mastered:[]).filter(id=>validIds.has(id)));
let corrections=saved.corrections&&typeof saved.corrections==='object'?saved.corrections:{};
let lesson=data.find(l=>l.id===saved.lesson)||data[0], book=lesson.book, index=Number.isInteger(saved.index)&&saved.index>=0&&saved.index<lesson.cues.length?saved.index:0;
const audio=$('#audio');
let token=0, finishedToken=-1, mode=null, active=false, completed=0, timer=null, boundaryTimer=null, loadingTimer=null, segmentEnd=0;
let screen=false,locked=false,auto=false,screenRepeats=3,rangeStart=0,rangeEnd=lesson.cues.length-1,loop=false,details=prefs.details;
let returnFocus=null,bodyScroll=0,introTimer=null,gesture=null,editing=null;
const time=n=>`${Math.floor(Math.max(0,n)/60)}:${String(Math.floor(Math.max(0,n)%60)).padStart(2,'0')}`;
const cue=()=>lesson.cues[index];
function save(){Object.assign(prefs,{lesson:lesson.id,index,favorites:[...favorites],mastered:[...mastered],corrections});try{localStorage.setItem(KEY,JSON.stringify(prefs));}catch{status('无法保存设置：浏览器存储空间不足。');}}
function status(text){$('#playStatus').textContent=text;$('#screenStatus').textContent=text;}
function bounds(c){const override=corrections[c.id];return override&&Number.isFinite(override.start)&&Number.isFinite(override.end)?override:c;}
function valid(c){const b=bounds(c);return b.start>=0&&b.start<b.end&&b.end<=lesson.duration+.01;}
function stop(){token++;clearTimeout(timer);clearInterval(boundaryTimer);clearTimeout(loadingTimer);audio.onloadedmetadata=null;audio.onseeked=null;audio.onended=null;audio.onerror=null;audio.pause();audio.muted=false;active=false;sync();}
function sync(){const text=active?'Ⅱ 暂停':'▶ 继续';$('#pause').textContent=text;$('#screenPause').textContent=text;$('#nowPlaying').textContent=`第 ${lesson.book} 册 · Lesson ${lesson.number} · ${mode==='lesson'?'整课':`第 ${index+1} 句`}`;$('#screenFavorite').textContent=favorites.has(cue().id)?'★ 已收藏':'☆ 收藏';$('#screenMastered').textContent=mastered.has(cue().id)?'✓ 已掌握':'○ 标为掌握';}
function finishSegment(my){if(my!==token||!active||finishedToken===my)return;finishedToken=my;clearInterval(boundaryTimer);audio.pause();audio.onended=null;completed++;
 if(mode==='lesson'){active=false;status('整课播放完成');sync();return;}
 const repeats=screen?(auto?screenRepeats:0):Number(prefs.repeat);
 if(repeats&&completed>=repeats){
  const last=screen?rangeEnd:lesson.cues.length-1;
  if(index<last){index++;completed=0;renderCurrent();}
  else if(screen&&loop){index=rangeStart;completed=0;renderCurrent();}
  else{active=false;status('本轮已完成');sync();return;}
 }
 status(`第 ${completed} 遍已完成`);timer=setTimeout(()=>{if(my===token)play('cues',false);},Math.max(0,Number(prefs.gap)||0)*1000);
}
function play(kind='cues',reset=true){
 if(kind==='cues'&&!valid(cue())){stop();status('本句时间轴超出录音，请先校准或选择整课播放。');return;}
 const previousCompleted=reset?0:completed;stop();completed=previousCompleted;mode=kind;active=true;
 const my=token, src=new URL(lesson.audio,location.href).href, b=bounds(cue());
 const start=kind==='lesson'?(reset?0:audio.currentTime):b.start;segmentEnd=kind==='lesson'?lesson.duration:b.end;
 const fail=err=>{if(my!==token)return;stop();status(err?.name==='NotAllowedError'?'浏览器需要授权，请点继续。':'音频加载失败，请检查网络或先下载本课，随后点继续。');};
 audio.onerror=()=>fail();audio.onended=()=>finishSegment(my);
 const monitor=()=>{if(my!==token||!active)return;audio.muted=false;clearTimeout(loadingTimer);clearInterval(boundaryTimer);boundaryTimer=setInterval(()=>{if(my===token&&active&&!audio.seeking&&audio.currentTime>=segmentEnd-.025)finishSegment(my);},25);status(kind==='lesson'?'整课播放中':`循环中 · 第 ${completed+1} 遍 · ${prefs.speed.toFixed(2)}×`);};
 const seek=()=>{if(my!==token||!active)return;audio.onseeked=monitor;try{if(Math.abs(audio.currentTime-start)<.02)monitor();else audio.currentTime=start;}catch(e){fail(e);}};
 audio.muted=true;audio.playbackRate=prefs.speed;audio.defaultPlaybackRate=prefs.speed;
 loadingTimer=setTimeout(()=>fail(),25000);status('音频加载中…');
 if(audio.src!==src){audio.src=src;audio.onloadedmetadata=seek;}else if(audio.readyState>=1)seek();else audio.onloadedmetadata=seek;
 // Called synchronously from click/swipe: preserve the iPhone gesture permission.
 try{const p=audio.play();p?.catch(fail);}catch(e){fail(e);}
 sync();
}
function togglePlay(){if(active){stop();status('已暂停');}else play(mode||'cues',false);}
function choose(l){stop();lesson=l;book=l.book;index=0;completed=0;rangeStart=0;rangeEnd=l.cues.length-1;auto=false;mode=null;save();render();}
function renderBooks(){$('#books').innerHTML=[1,2,3,4].map(b=>`<button data-book="${b}" class="${book===b?'active':''}" aria-pressed="${book===b}">第 ${b} 册<small>${data.filter(l=>l.book===b).length} 课 · ${['基础入门','实践进阶','熟练运用','流利表达'][b-1]}</small></button>`).join('');}
function renderLessons(){const q=$('#search').value.trim().toLowerCase();const list=data.filter(l=>l.book===book&&(!$('#onlyFavorites').checked||l.cues.some(c=>favorites.has(c.id)))&&(!q||`${l.number} ${l.title} ${l.cues.map(c=>c.text).join(' ')}`.toLowerCase().includes(q)));$('#lessons').innerHTML=list.map(l=>`<button data-lesson="${l.id}" class="${lesson.id===l.id?'active':''}" aria-current="${lesson.id===l.id?'true':'false'}"><small>LESSON ${l.number} · ${l.cues.length} 句</small>${esc(l.title)}</button>`).join('')||'<p>没有找到匹配课程。</p>';}
function renderTranscript(){$('#transcript').innerHTML=lesson.cues.map((c,i)=>`<article class="cue ${i===index?'current':''} ${mastered.has(c.id)?'mastered':''}" data-cue="${i}"><div class="cueTop"><span>${String(i+1).padStart(2,'0')} · ${time(bounds(c).start)}–${time(bounds(c).end)}</span><span class="badTime">${!valid(c)?'时间轴待校准':c.needsReview?'自动对齐待复核':''}</span></div><p lang="en">${esc(c.text)}</p><div class="cueActions"><button data-action="play">▶ 播放</button><button data-action="screen">↕ 大屏</button><button data-action="favorite" aria-pressed="${favorites.has(c.id)}">${favorites.has(c.id)?'★ 已收藏':'☆ 收藏'}</button><button data-action="mastered" aria-pressed="${mastered.has(c.id)}">${mastered.has(c.id)?'✓ 已掌握':'○ 标为掌握'}</button><button data-action="timing">校准</button></div></article>`).join('');}
function renderCurrent(){document.querySelectorAll('.cue.current').forEach(el=>el.classList.remove('current'));$(`[data-cue="${index}"]`)?.classList.add('current');if(screen)renderScreen();save();sync();}
function render(){renderBooks();renderLessons();$('#lessonLabel').textContent=`BOOK ${book} · LESSON ${lesson.number}`;$('#lessonTitle').textContent=lesson.title;$('#sourceWarning').textContent=lesson.aligned?'按英文完整句切分，时间轴由本地声学模型重新对齐；低置信度句子已标注，可手动复核。':'时间轴来自原 LRC，尚未完成逐句对齐；整课原声可直接播放。';renderTranscript();fillDownloads();fillRange();renderCurrent();}
function step(delta){const next=Math.max(screen?rangeStart:0,Math.min(screen?rangeEnd:lesson.cues.length-1,index+delta));if(next===index)return;stop();index=next;completed=0;renderCurrent();play();}
function mark(set,id){set.has(id)?set.delete(id):set.add(id);save();renderTranscript();renderLessons();sync();}
function renderScreen(){const c=cue();$('#screenLesson').textContent=`第 ${book} 册 · Lesson ${lesson.number} · ${lesson.title}`;$('#screenCounter').textContent=`${index+1} / ${lesson.cues.length} · 区间 ${rangeStart+1}–${rangeEnd+1}`;$('#cueLabel').textContent=`SENTENCE ${index+1}${c.needsReview?' · 对齐待复核':''}`;$('#screenText').textContent=c.text;$('#screenText').hidden=!!prefs.hide;$('#reveal').hidden=!prefs.hide;details=!!prefs.details;renderContext();}
function renderContext(){$('#screenContext').hidden=!details;$('#detailsToggle').textContent=details?'收起上下文':'展开上下文';$('#detailsToggle').setAttribute('aria-expanded',String(details));$('#screenContext').innerHTML=lesson.cues.slice(Math.max(0,index-1),index+2).map(c=>`<p lang="en">${c.id===cue().id?'<b>':''}${esc(c.text)}${c.id===cue().id?'</b>':''}</p>`).join('');}
function fillRange(){$('#rangeStart').value=rangeStart+1;$('#rangeEnd').value=rangeEnd+1;$('#rangeStart').max=$('#rangeEnd').max=lesson.cues.length;$('#autoNext').checked=auto;$('#screenRepeats').value=screenRepeats;$('#loopRange').checked=loop;$('#rangeSummary').textContent=auto?`自动切换 · 每句 ${screenRepeats} 遍 · ${rangeStart+1}–${rangeEnd+1} · ${loop?'区间循环':'末尾停止'}`:`手动切换 · 当前句循环 · ${rangeStart+1}–${rangeEnd+1}`;}
function openScreen(i=index){returnFocus=document.activeElement;bodyScroll=scrollY;index=i;screen=true;locked=false;$('#screen').hidden=false;$('#screen').classList.remove('locked');$('#lock').textContent='锁定';$('#lock').setAttribute('aria-pressed','false');$('#app').inert=$('#playerBar').inert=true;document.body.classList.add('screenOpen');$('#screenPlayback').open=false;renderScreen();fillRange();$('#screenCard').focus();play();
 if(!prefs.intro){prefs.intro=true;save();$('#swipeIntro').hidden=false;introTimer=setTimeout(()=>$('#swipeIntro').hidden=true,1500);}
 if($('#screen').requestFullscreen)$('#screen').requestFullscreen().then(()=>{if(!screen&&document.fullscreenElement===$('#screen'))document.exitFullscreen().catch(()=>{});}).catch(()=>{});
}
function closeScreen(){if(locked)return;stop();screen=false;clearTimeout(introTimer);$('#swipeIntro').hidden=true;$('#screen').hidden=true;$('#app').inert=$('#playerBar').inert=false;document.body.classList.remove('screenOpen');if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});window.scrollTo(0,bodyScroll);returnFocus?.isConnected&&returnFocus.focus();}
function lock(){locked=!locked;$('#screen').classList.toggle('locked',locked);$('#lock').textContent=locked?'解锁':'锁定';$('#lock').setAttribute('aria-pressed',String(locked));$('#lockHint').textContent=locked?'已锁定 · 仅可上下滑动 · 点击右上角解锁':'上滑下一句 · 下滑上一句';for(const el of document.querySelectorAll('.screenSettings,#exitScreen,.screenBottom label,.two,#screenHero button'))el.inert=locked;$('#screenCard').focus();}
$('#books').onclick=e=>{const b=e.target.closest('[data-book]');if(b){book=Number(b.dataset.book);renderBooks();renderLessons();fillDownloads();}};
$('#lessons').onclick=e=>{const el=e.target.closest('[data-lesson]');if(el)choose(data.find(l=>l.id===el.dataset.lesson));};
$('#search').oninput=renderLessons;$('#onlyFavorites').onchange=renderLessons;
$('#transcript').onclick=e=>{const b=e.target.closest('[data-action]'),row=b?.closest('[data-cue]');if(!b||!row)return;const i=Number(row.dataset.cue),c=lesson.cues[i];if(b.dataset.action==='favorite')return mark(favorites,c.id);if(b.dataset.action==='mastered')return mark(mastered,c.id);if(b.dataset.action==='timing'){editing=c;$('#timingText').textContent=c.text;$('#timingStart').value=bounds(c).start;$('#timingEnd').value=bounds(c).end;$('#timingError').textContent='';$('#timingDialog').showModal();return;}index=i;renderCurrent();if(b.dataset.action==='screen')openScreen(i);else play();};
$('#playLesson').onclick=()=>play('lesson');$('#playCues').onclick=()=>play();$('#pause').onclick=togglePlay;$('#screenPause').onclick=togglePlay;
$('#openScreen').onclick=()=>openScreen();$('#exitScreen').onclick=closeScreen;$('#lock').onclick=lock;
$('#reveal').onclick=()=>{$('#screenText').hidden=false;$('#reveal').hidden=true;};
$('#screenFavorite').onclick=()=>mark(favorites,cue().id);$('#screenMastered').onclick=()=>mark(mastered,cue().id);
$('#detailsToggle').onclick=()=>{details=!details;renderContext();};
$('#screenForm').onsubmit=e=>{e.preventDefault();const a=Number($('#rangeStart').value),b=Number($('#rangeEnd').value),r=Number($('#screenRepeats').value);if(![a,b,r].every(Number.isInteger)||a<1||b>lesson.cues.length||a>b||r<1||r>100){$('#rangeError').textContent='请输入有效的课内句子区间和 1–100 遍次数。';return;}rangeStart=a-1;rangeEnd=b-1;screenRepeats=r;auto=$('#autoNext').checked;loop=$('#loopRange').checked;index=rangeStart;$('#rangeError').textContent='';fillRange();$('#screenPlayback').open=false;renderCurrent();play();};
for(const id of ['speed','screenSpeed']){$('#'+id).innerHTML=Array.from({length:31},(_,i)=>{const v=((50+5*i)/100).toFixed(2);return `<option value="${v}">${v}×</option>`;}).join('');$('#'+id).value=prefs.speed.toFixed(2);$('#'+id).onchange=e=>{prefs.speed=Number(e.target.value);audio.playbackRate=audio.defaultPlaybackRate=prefs.speed;$('#speed').value=$('#screenSpeed').value=prefs.speed.toFixed(2);save();};}
$('#gap').value=String(prefs.gap);$('#gap').onchange=e=>{prefs.gap=Number(e.target.value);save();};$('#repeat').value=String(prefs.repeat);$('#repeat').onchange=e=>{prefs.repeat=Number(e.target.value);save();};
function applyDisplay(){document.body.classList.toggle('dark',prefs.theme==='dark');$('#screen').style.setProperty('--font',prefs.font/100);$('#fontSize').value=prefs.font;$('#fontValue').textContent=prefs.font+'%';$('#hideText').checked=!!prefs.hide;$('#defaultDetails').checked=!!prefs.details;}
$('#theme').onclick=()=>{prefs.theme=prefs.theme==='dark'?'light':'dark';applyDisplay();save();};$('#fontSize').oninput=e=>{prefs.font=Number(e.target.value);applyDisplay();save();};$('#hideText').onchange=e=>{prefs.hide=e.target.checked;renderScreen();save();};$('#defaultDetails').onchange=e=>{prefs.details=e.target.checked;details=prefs.details;renderContext();save();};
audio.ontimeupdate=()=>{$('#seek').max=lesson.duration;$('#seek').value=audio.currentTime;$('#clock').textContent=`${time(audio.currentTime)} / ${time(lesson.duration)}`;if(mode==='lesson'&&active){const i=lesson.cues.findIndex(c=>audio.currentTime>=bounds(c).start&&audio.currentTime<bounds(c).end);if(i>=0&&i!==index){index=i;renderCurrent();}}};
$('#seek').oninput=e=>{const position=Number(e.target.value);if(audio.src!==new URL(lesson.audio,location.href).href)return;stop();mode='lesson';audio.currentTime=position;status('已定位，点击整课播放将从头开始。');};
$('#timingForm').onsubmit=e=>{e.preventDefault();const start=Number($('#timingStart').value),end=Number($('#timingEnd').value);if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>lesson.duration){$('#timingError').textContent=`需满足 0 ≤ 开始 < 结束 ≤ ${lesson.duration} 秒。`;return;}corrections[editing.id]={start,end};save();stop();renderTranscript();$('#timingDialog').close();};$('#closeTiming').onclick=()=>$('#timingDialog').close();$('#resetTiming').onclick=()=>{delete corrections[editing.id];save();stop();renderTranscript();$('#timingDialog').close();};
for(const type of ['click','input','change','submit'])$('#screen').addEventListener(type,e=>{if(locked&&!e.target.closest('#lock')){e.preventDefault();e.stopImmediatePropagation();}},true);
$('#screenCard').addEventListener('touchstart',e=>{if(e.touches.length!==1||e.target.closest('button')){gesture=null;return;}const scroll=e.target.closest('#screenContext,#screenHero');gesture={x:e.touches[0].clientX,y:e.touches[0].clientY,scroll,top:scroll?.scrollTop||0,dy:0,kind:null};},{passive:true});
$('#screenCard').addEventListener('touchmove',e=>{if(!gesture||e.touches.length!==1)return;const g=gesture,dx=e.touches[0].clientX-g.x,dy=e.touches[0].clientY-g.y;g.dy=dy;if(!g.kind&&Math.max(Math.abs(dx),Math.abs(dy))>10){const can=g.scroll&&(dy<0?g.top+g.scroll.clientHeight<g.scroll.scrollHeight-2:g.top>0);g.kind=Math.abs(dx)>Math.abs(dy)?'ignore':!locked&&can?'scroll':'swipe';}if(g.kind==='scroll'){e.preventDefault();g.scroll.scrollTop=g.top-dy;}if(g.kind==='swipe')e.preventDefault();},{passive:false});
$('#screenCard').addEventListener('touchend',()=>{const g=gesture;gesture=null;if(g?.kind==='swipe'&&Math.abs(g.dy)>55)step(g.dy<0?1:-1);});$('#screenCard').addEventListener('touchcancel',()=>gesture=null);
let wheelAt=0;$('#screenCard').addEventListener('wheel',e=>{if(e.ctrlKey||Math.abs(e.deltaX)>Math.abs(e.deltaY))return;const el=e.target.closest('#screenContext,#screenHero');if(!locked&&el&&(e.deltaY>0?el.scrollTop+el.clientHeight<el.scrollHeight-2:el.scrollTop>0))return;e.preventDefault();if(Date.now()-wheelAt>350&&Math.abs(e.deltaY)>25){wheelAt=Date.now();step(e.deltaY>0?1:-1);}},{passive:false});
document.addEventListener('keydown',e=>{if(!screen||$('#timingDialog').open)return;if(locked){if(e.key==='Tab'){e.preventDefault();$('#lock').focus();}else if(!(e.target===$('#lock')&&[' ','Enter'].includes(e.key)))e.preventDefault();return;}if(e.key==='Escape'){e.preventDefault();closeScreen();return;}if(e.key==='Tab'){const els=[...$('#screen').querySelectorAll('button,input,select,summary,[tabindex="0"]')].filter(el=>!el.disabled&&el.getClientRects().length);if(e.shiftKey&&document.activeElement===els[0]){e.preventDefault();els.at(-1).focus();}else if(!e.shiftKey&&document.activeElement===els.at(-1)){e.preventDefault();els[0].focus();}return;}if(e.target.closest('input,select,summary,button'))return;if(e.key==='ArrowDown'){e.preventDefault();step(1);}if(e.key==='ArrowUp'){e.preventDefault();step(-1);}if(e.code==='Space'){e.preventDefault();togglePlay();}},true);
document.addEventListener('visibilitychange',()=>{if(document.hidden&&active){stop();status('切到后台已暂停，请点继续。');}});
$('#exportProgress').onclick=()=>{save();const url=URL.createObjectURL(new Blob([JSON.stringify({version:1,...prefs},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='nce-learning-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('#importProgress').onchange=async e=>{try{const f=e.target.files[0];if(!f||f.size>5e6)throw Error();const p=JSON.parse(await f.text());if(p.version!==1||!Array.isArray(p.favorites)||!Array.isArray(p.mastered))throw Error();favorites.clear();mastered.clear();p.favorites.filter(id=>validIds.has(id)).forEach(id=>favorites.add(id));p.mastered.filter(id=>validIds.has(id)).forEach(id=>mastered.add(id));corrections={};for(const [id,b] of Object.entries(p.corrections||{})){if(validIds.has(id)&&Number.isFinite(b?.start)&&Number.isFinite(b?.end)&&b.start>=0&&b.end>b.start)corrections[id]=b;}save();render();$('#backupStatus').textContent='已恢复收藏、掌握记录与时间校准。';}catch{$('#backupStatus').textContent='备份无效，请选择本项目导出的 JSON 文件。';}};
// Download whole source lessons so all sentence ranges share one cached recording.
let downloadPort=null,downloadTimer=null;
function fillDownloads(){if(downloadPort)return;const lessons=data.filter(l=>l.book===book);const html=lessons.map(l=>`<option value="${l.id}">Lesson ${l.number}</option>`).join('');$('#downloadStart').innerHTML=$('#downloadEnd').innerHTML=html;const id=lessons.some(l=>l.id===lesson.id)?lesson.id:lessons[0].id;$('#downloadStart').value=$('#downloadEnd').value=id;estimate();}
function selectedDownloads(){const list=data.filter(l=>l.book===book),a=list.findIndex(l=>l.id===$('#downloadStart').value),b=list.findIndex(l=>l.id===$('#downloadEnd').value);return a<0||b<a?[]:list.slice(a,b+1);}
function estimate(){const list=selectedDownloads();$('#downloadEstimate').textContent=list.length?`${list.length} 课 · 原声音频约 ${(list.reduce((n,l)=>n+l.bytes,0)/1048576).toFixed(1)} MB（已缓存的不会重复下载）`:'结束课不能早于起始课。';}
$('#downloadStart').onchange=$('#downloadEnd').onchange=estimate;
function endDownload(text){clearTimeout(downloadTimer);downloadPort?.close();downloadPort=null;for(const id of ['downloadStart','downloadEnd','download'])$('#'+id).disabled=false;$('#cancelDownload').hidden=true;$('#downloadStatus').textContent=text;}
$('#downloadForm').onsubmit=e=>{e.preventDefault();if(downloadPort)return;const lessons=selectedDownloads();if(!lessons.length){$('#downloadStatus').textContent='请选择有效课程区间。';return;}if(!navigator.serviceWorker?.controller){$('#downloadStatus').textContent='离线下载需要 HTTPS 网页及缓存支持；首次打开请等待缓存就绪后刷新。';return;}const channel=new MessageChannel();downloadPort=channel.port1;for(const id of ['downloadStart','downloadEnd','download'])$('#'+id).disabled=true;$('#cancelDownload').hidden=false;$('#downloadProgress').hidden=false;$('#downloadProgress').max=lessons.length;$('#downloadProgress').value=0;const watch=()=>{clearTimeout(downloadTimer);downloadTimer=setTimeout(()=>{downloadPort?.postMessage('cancel');endDownload('下载中断，可重试补齐已有缓存。');},90000);};watch();downloadPort.onmessage=({data:m})=>{watch();$('#downloadProgress').value=m.loaded||0;const text=`${m.loaded||0}/${lessons.length} 课已缓存`;if(m.done||m.error||m.cancelled)endDownload(m.error||`${m.cancelled?'已取消':'下载完成'} · ${text}，已下载部分保留。`);else $('#downloadStatus').textContent=text;};navigator.serviceWorker.controller.postMessage({type:'DOWNLOAD',ids:lessons.map(l=>l.id)},[channel.port2]);};
$('#cancelDownload').onclick=()=>downloadPort?.postMessage('cancel');window.addEventListener('pagehide',()=>{stop();downloadPort?.postMessage('cancel');if(downloadPort)endDownload('离开页面后下载已中断，可重试补齐。');});
$('#totals').textContent=`4 册 · ${data.length} 课 · ${data.reduce((n,l)=>n+l.cues.length,0).toLocaleString()} 句 · 英文原文与原声录音`;
applyDisplay();render();if('serviceWorker'in navigator&&/^https?:$/.test(location.protocol))navigator.serviceWorker.register('./sw.js').catch(()=>{});
})();
