/* One persistent media element for Safari; all text comes from the local corpus. */
(async () => {
'use strict';
const $=s=>document.querySelector(s), data=NCE_DATA.lessons, KEY='nce-study-v1';
const translations=window.NCE_TRANSLATIONS||{},dictionary=window.NCE_DICTIONARY||{};
const catalogController=new AbortController(),catalogTimeout=setTimeout(()=>catalogController.abort(),15000);
const voiceData=await fetch('./voice-index.json',{signal:catalogController.signal}).then(r=>{if(!r.ok)throw Error();return r.json();}).catch(()=>({ready:false,voices:[],cues:{},assets:{}})).finally(()=>clearTimeout(catalogTimeout));
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let saved;try{saved=JSON.parse(localStorage.getItem(KEY)||'{}');}catch{saved={};}saved=saved&&typeof saved==='object'?saved:{};
const validIds=new Set(data.flatMap(l=>l.cues.map(c=>c.id)));
const sourceParts=new Map();for(const l of data)for(const c of l.cues){const id=c.sourceId||c.id;if(!sourceParts.has(id))sourceParts.set(id,[]);sourceParts.get(id).push(c);}
const migrateMarks=ids=>(Array.isArray(ids)?ids:[]).flatMap(id=>validIds.has(id)?[id]:(sourceParts.get(id)||[]).map(c=>c.id));
const prefs={speed:1,gap:.5,repeat:0,font:100,translationFont:100,contextFont:100,voice:'original',hide:false,hideTranslation:false,showTranslations:true,details:false,theme:'light',intro:false,...saved};
const voiceModes=new Set(['original',...(voiceData.ready?['gb-cycle','us-cycle','all-cycle',...voiceData.voices.map(v=>v.id)]:[])]);
if(!voiceModes.has(prefs.voice))prefs.voice='original';
prefs.contextFont=Number.isFinite(+prefs.contextFont)&&+prefs.contextFont>=80&&+prefs.contextFont<=160?+prefs.contextFont:100;
prefs.translationFont=Number.isFinite(+prefs.translationFont)&&+prefs.translationFont>=80&&+prefs.translationFont<=160?+prefs.translationFont:100;
prefs.speed=Number.isFinite(+prefs.speed)&&+prefs.speed>=.5&&+prefs.speed<=2?+prefs.speed:1;
prefs.font=Number.isFinite(+prefs.font)&&+prefs.font>=80&&+prefs.font<=160?+prefs.font:100;
const favorites=new Set(migrateMarks(saved.favorites));
const mastered=new Set(migrateMarks(saved.mastered));
let corrections=saved.corrections&&typeof saved.corrections==='object'?saved.corrections:{};
let lesson=data.find(l=>l.id===saved.lesson)||data[0], book=lesson.book, index=Number.isInteger(saved.index)&&saved.index>=0&&saved.index<lesson.cues.length?saved.index:0;
if(saved.cueId){const found=lesson.cues.findIndex(c=>c.id===saved.cueId||c.sourceId===saved.cueId);if(found>=0)index=found;}
else if((saved.dataVersion||2)<3&&NCE_DATA.version>=3){const found=lesson.cues.findIndex(c=>c.sourceIndex===saved.index);if(found>=0)index=found;}
const audio=$('#audio');
let token=0, finishedToken=-1, mode=null, active=false, completed=0, timer=null, boundaryTimer=null, loadingTimer=null, segmentEnd=0;
let voiceTurn=0,playingAsset=null;
let screen=false,locked=false,auto=false,screenRepeats=3,rangeStart=0,rangeEnd=lesson.cues.length-1,loop=false,details=prefs.details;
let returnFocus=null,bodyScroll=0,introTimer=null,gesture=null,editing=null;
const time=n=>`${Math.floor(Math.max(0,n)/60)}:${String(Math.floor(Math.max(0,n)%60)).padStart(2,'0')}`;
const cue=()=>lesson.cues[index];
const translation=c=>translations[c.id]||['译文暂不可用',1];
function renderWords(source){const re=/[A-Za-z]+(?:['’][A-Za-z]+)?/g;let html='',last=0,match;while((match=re.exec(source))){html+=esc(source.slice(last,match.index));html+=`<button class="wordToken" type="button" data-word="${esc(match[0])}" aria-label="查询 ${esc(match[0])} 的词义">${esc(match[0])}</button>`;last=re.lastIndex;}return html+esc(source.slice(last));}
function phraseList(source){
 const words=(source.match(/[A-Za-z]+(?:['’][A-Za-z]+)?/g)||[]).map(w=>w.toLowerCase().replaceAll('’',"'"));
 const found=[],used=new Set();
 for(let n=4;n>=2;n--)for(let i=0;i+n<=words.length;i++){
  if([...Array(n)].some((_,j)=>used.has(i+j)))continue;
  const term=words.slice(i,i+n).join(' ');
  if(!Object.prototype.hasOwnProperty.call(dictionary,term))continue;
  if(!words.slice(i,i+n).some(w=>w.length>=4))continue;
  found.push({term,i});for(let j=0;j<n;j++)used.add(i+j);
 }
 return found.sort((a,b)=>a.i-b.i).slice(0,4).map(({term})=>`<button class="phraseToken" type="button" data-word="${esc(term)}" aria-label="查询短语 ${esc(term)}">${esc(term)}</button>`).join('');
}
function save(){Object.assign(prefs,{lesson:lesson.id,index,cueId:cue().id,dataVersion:NCE_DATA.version,favorites:[...favorites],mastered:[...mastered],corrections});try{localStorage.setItem(KEY,JSON.stringify(prefs));}catch{status('无法保存设置：浏览器存储空间不足。');}}
function status(text){for(const id of ['playStatus','screenStatus'])if($('#'+id).textContent!==text)$('#'+id).textContent=text;}
function bounds(c){const override=corrections[c.id];return override&&Number.isFinite(override.start)&&Number.isFinite(override.end)?override:c;}
function valid(c){const b=bounds(c);return b.start>=0&&b.start<b.end&&b.end<=lesson.duration+.01;}
function voiceAsset(c,turn){
 if(prefs.voice==='original')return null;
 const choices=prefs.voice.endsWith('-cycle')?voiceData.voices.filter(v=>prefs.voice==='all-cycle'||v.id.startsWith(prefs.voice.slice(0,2)+'-')):voiceData.voices.filter(v=>v.id===prefs.voice);
 const voice=choices[turn%choices.length],key=voiceData.cues[c.id],asset=voice&&voiceData.assets[`${voice.id}/${key}`];
 return asset?{path:`audio/tts/${voice.id}/${key}.m4a`,duration:asset[1],label:voice.label}:false;
}
function stop(){token++;active=false;clearTimeout(timer);clearInterval(boundaryTimer);clearTimeout(loadingTimer);for(const event of ['loadedmetadata','loadeddata','canplay','progress','playing','seeked','waiting','ended','error'])audio['on'+event]=null;audio.pause();sync();}
function sync(){const text=active?'Ⅱ 暂停':mode?'▶ 继续':'▶ 播放';$('#pause').textContent=text;$('#screenPause').textContent=text;$('#previousCue').disabled=index===0;$('#nextCue').disabled=index===lesson.cues.length-1;$('#playerBar .playerNow').classList.toggle('playing',active);$('#nowPlaying').textContent=`第 ${lesson.book} 册 · Lesson ${lesson.number} · ${mode==='lesson'?'整课':`第 ${index+1} 句`}`;$('#screenFavorite').textContent=favorites.has(cue().id)?'★ 已收藏':'☆ 收藏';$('#screenMastered').textContent=mastered.has(cue().id)?'✓ 已掌握':'○ 标为掌握';}
function finishSegment(my){if(my!==token||!active||finishedToken===my)return;finishedToken=my;clearInterval(boundaryTimer);audio.pause();audio.onended=null;completed++;voiceTurn++;
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
 if(reset)voiceTurn=0;
 const asset=kind==='lesson'?null:voiceAsset(cue(),voiceTurn);
 if(asset===false){stop();status('该音色文件缺失，请联网重试或改选原版录音。');return;}
 if(kind==='cues'&&!asset&&!valid(cue())){stop();status('本句时间轴超出录音，请先校准或选择整课播放。');return;}
 const previousCompleted=reset?0:completed;stop();completed=previousCompleted;mode=kind;active=true;
 playingAsset=asset;$('#seek').disabled=!!asset;
 const my=token, src=new URL(asset?asset.path:lesson.audio,location.href).href, b=bounds(cue());
 const start=asset?0:kind==='lesson'?(reset?0:audio.currentTime):b.start;segmentEnd=asset?asset.duration:kind==='lesson'?lesson.duration:b.end;
 const fail=err=>{if(my!==token||finishedToken===my)return;stop();status(err?.name==='NotAllowedError'?'浏览器需要授权，请点继续。':'音频加载失败，请检查网络或先下载本课，随后点继续。');};
 audio.onerror=()=>fail();audio.onended=()=>{if(asset||(located&&audio.currentTime>=segmentEnd-.08))finishSegment(my);};
 let located=false,seekRequested=false,lastSeek=-Infinity,lastTime=start,lastProgress=performance.now();
 const playingText=()=>status(kind==='lesson'?'整课原版录音播放中':`循环中 · 第 ${completed+1} 遍 · ${asset?asset.label+' · ':''}${prefs.speed.toFixed(2)}×`);
 const inspect=()=>{
  if(my!==token||!active||finishedToken===my)return;
  const now=performance.now();
  if(!located){
   if(audio.readyState<1)return;
   const atStart=audio.currentTime>=start-.06&&audio.currentTime<Math.min(segmentEnd,start+.5);
   // Safari may ignore a seek while only metadata (not seekable data) is ready.
   // Recheck state rather than depending on a single seeked/canplay event.
   if((!seekRequested||!atStart)&&!audio.seeking&&now-lastSeek>=300){
    lastSeek=now;seekRequested=true;
    try{if(Math.abs(audio.currentTime-start)>.015)audio.currentTime=start;}catch{return;}
   }
   if(!seekRequested||audio.seeking||audio.paused||audio.readyState<2||audio.currentTime<start-.06||audio.currentTime>=Math.min(segmentEnd,start+.5))return;
   located=true;lastTime=audio.currentTime;lastProgress=now;clearTimeout(loadingTimer);playingText();
  }
  if(!audio.seeking&&audio.currentTime>=segmentEnd){finishSegment(my);return;}
  if(audio.currentTime>lastTime+.005){lastTime=audio.currentTime;lastProgress=now;playingText();}
  else if(now-lastProgress>25000)fail();
 };
 for(const event of ['loadedmetadata','loadeddata','canplay','progress','playing','seeked'])audio['on'+event]=inspect;
 audio.onwaiting=()=>{if(my===token&&active&&located)status('正在缓冲，请稍候…');};
 // Obtain audible playback permission in the original user gesture. Never start
 // muted and unmute from an asynchronous seek callback (Safari may suspend it).
 audio.muted=false;audio.playbackRate=prefs.speed;audio.defaultPlaybackRate=prefs.speed;
 loadingTimer=setTimeout(()=>fail(),25000);status('音频加载中…');
 if(audio.src!==src){audio.src=src;audio.load();}
 // A cue inside a whole-lesson recording can begin many seconds after zero.
 // Attempt the position before the gesture-authorized play() call, then let
 // inspect() retry if WebKit discards this early seek while loading metadata.
 if(start>0&&Math.abs(audio.currentTime-start)>.015){try{audio.currentTime=start;}catch{}}
 inspect();
 boundaryTimer=setInterval(inspect,25);
 try{const p=audio.play();p?.then(inspect).catch(fail);}catch(e){fail(e);}
 sync();
}
function togglePlay(){if(active){stop();status('已暂停');}else play(mode||'cues',false);}
function choose(l){stop();playingAsset=null;$('#seek').disabled=false;lesson=l;book=l.book;index=0;completed=0;rangeStart=0;rangeEnd=l.cues.length-1;auto=false;mode=null;save();render();}
function renderBooks(){$('#books').innerHTML=[1,2,3,4].map(b=>`<button data-book="${b}" class="${book===b?'active':''}" aria-pressed="${book===b}">第 ${b} 册<small>${data.filter(l=>l.book===b).length} 课 · ${['基础入门','实践进阶','熟练运用','流利表达'][b-1]}</small></button>`).join('');}
function renderLessons(){const q=$('#search').value.trim().toLowerCase();const list=data.filter(l=>l.book===book&&(!$('#onlyFavorites').checked||l.cues.some(c=>favorites.has(c.id)))&&(!q||`${l.number} ${l.title} ${l.cues.map(c=>c.text).join(' ')}`.toLowerCase().includes(q)));$('#lessonChoice').textContent=`选课 · 第 ${book} 册 · 当前 Lesson ${lesson.number}`;$('#lessonChoiceCount').textContent=`${list.length} 课`;$('#lessons').innerHTML=list.map(l=>`<button data-lesson="${l.id}" class="${lesson.id===l.id?'active':''}" aria-current="${lesson.id===l.id?'true':'false'}"><small>LESSON ${l.number} · ${l.cues.length} 句</small>${esc(l.title)}</button>`).join('')||'<p>没有找到匹配课程。</p>';}
const partLabel=c=>c.parts>1?`原句 ${c.sourceIndex+1} · 片段 ${c.part}/${c.parts}`:'';
const originalText=c=>(sourceParts.get(c.sourceId||c.id)||[c]).map(p=>p.text).join(' ');
function renderTranscript(){$('#transcript').innerHTML=lesson.cues.map((c,i)=>`<article class="cue ${i===index?'current':''} ${mastered.has(c.id)?'mastered':''}" data-cue="${i}"><div class="cueTop"><span>${String(i+1).padStart(2,'0')} · ${time(bounds(c).start)}–${time(bounds(c).end)}${c.parts>1?` · ${partLabel(c)}`:''}</span><span class="badTime">${!valid(c)?'时间轴待校准':c.needsReview?'自动对齐待复核':''}</span></div><p class="cueEnglish" lang="en">${renderWords(c.text)}</p>${phraseList(c.text)?`<div class="phraseList"><span>短语</span>${phraseList(c.text)}</div>`:''}<p class="cueZh" lang="zh-CN" ${prefs.showTranslations?'':'hidden'}>${esc(translation(c)[0])}${translation(c)[1]?'<span class="translationBadge">机译</span>':''}</p>${c.parts>1?`<details class="originalSentence"><summary>查看完整原句</summary><p lang="en">${esc(originalText(c))}</p></details>`:''}<div class="cueActions"><button data-action="play">▶ 播放</button><button data-action="favorite" aria-pressed="${favorites.has(c.id)}">${favorites.has(c.id)?'★ 已收藏':'☆ 收藏'}</button><button data-action="mastered" aria-pressed="${mastered.has(c.id)}">${mastered.has(c.id)?'✓ 已掌握':'○ 标为掌握'}</button><button data-action="screen">↕ 大屏</button><button data-action="timing">校准</button></div></article>`).join('');}
function renderCurrent(){document.querySelectorAll('.cue.current').forEach(el=>el.classList.remove('current'));$(`[data-cue="${index}"]`)?.classList.add('current');if(screen)renderScreen();save();sync();}
function updateProgress(){$('#progressCount').textContent=mastered.size;$('#progressTotal').textContent=`/ ${validIds.size}`;}
function render(){renderBooks();renderLessons();updateProgress();$('#lessonLabel').textContent=`BOOK ${book} · LESSON ${lesson.number}`;$('#lessonTitle').textContent=lesson.title;$('#sourceWarning').textContent=lesson.alignmentMethod?'长句按从句和停顿拆为片段，可展开完整原句；录音已逐词重新对齐，待复核项仍可手动校准。':lesson.aligned?'按英文完整句切分，时间轴由本地声学模型重新对齐；低置信度句子已标注，可手动复核。':'时间轴来自原 LRC，尚未完成逐句对齐；整课原声可直接播放。';renderTranscript();fillDownloads();fillRange();renderCurrent();}
function step(delta){const next=Math.max(screen?rangeStart:0,Math.min(screen?rangeEnd:lesson.cues.length-1,index+delta));if(next===index)return;stop();index=next;completed=0;renderCurrent();play();}
function mark(set,id){set.has(id)?set.delete(id):set.add(id);save();renderTranscript();renderLessons();updateProgress();sync();}
function fillScreenCourse(){const select=$('#screenLessonSelect');if(select.dataset.currentBook!==String(book)){select.innerHTML=data.filter(l=>l.book===book).map(l=>`<option value="${l.id}">第${l.number}课</option>`).join('');select.dataset.currentBook=String(book);}select.value=lesson.id;if(select.dataset.currentLesson!==lesson.id&&!voiceDownloadPort){for(const id of ['voiceDownloadStart','voiceDownloadEnd'])$('#'+id).max=lesson.cues.length;$('#voiceDownloadStart').value=index+1;$('#voiceDownloadEnd').value=Math.min(lesson.cues.length,index+10);select.dataset.currentLesson=lesson.id;}}
function renderScreen(){fillScreenCourse();const c=cue();$('#screenLesson').textContent=`第 ${book} 册 · Lesson ${lesson.number} · ${lesson.title}`;$('#screenCounter').textContent=`${index+1} / ${lesson.cues.length}`;$('#screenProgressFill').style.width=`${(index+1)/lesson.cues.length*100}%`;for(const [key,value] of Object.entries({'aria-valuemin':1,'aria-valuemax':lesson.cues.length,'aria-valuenow':index+1}))$('#screenProgressBar').setAttribute(key,value);$('#cueLabel').textContent=`${c.parts>1?partLabel(c):`SENTENCE ${index+1}`}${c.needsReview?' · 对齐待复核':''}${translation(c)[1]?' · 机译':''}`;$('#screenText').innerHTML=renderWords(c.text);$('#screenText').hidden=!!prefs.hide;$('#reveal').hidden=!prefs.hide;$('#screenPhrases').innerHTML=phraseList(c.text);$('#screenPhrases').hidden=!!prefs.hide||!$('#screenPhrases').innerHTML;$('#screenTranslation').textContent=translation(c)[0];$('#screenTranslation').hidden=!!prefs.hideTranslation;$('#translationReveal').hidden=!prefs.hideTranslation;details=!!prefs.details;renderContext();}
function renderContext(){const zhHidden=$('#screenTranslation').hidden?' hidden':'';$('#screenContext').hidden=!details;$('#screenCard').classList.toggle('withDetails',details);$('#detailsToggle').textContent=details?'收起上下文':'展开上下文';$('#detailsToggle').setAttribute('aria-expanded',String(details));$('#screenContext').innerHTML=cue().parts>1?`<small>完整原句</small><p lang="en">${esc(originalText(cue()))}</p><p lang="zh-CN"${zhHidden}>${esc((sourceParts.get(cue().sourceId)||[cue()]).map(c=>translation(c)[0]).join(''))}</p>`:lesson.cues.slice(Math.max(0,index-1),index+2).map(c=>`<div class="contextPair ${c.id===cue().id?'contextCurrent':''}"><p lang="en">${esc(c.text)}</p><p lang="zh-CN"${zhHidden}>${esc(translation(c)[0])}</p></div>`).join('');}
let wordReturnFocus=null;
const hasTerm=key=>Object.prototype.hasOwnProperty.call(dictionary,key);
function lookupTerm(raw){
 const key=String(raw).toLowerCase().replaceAll('’',"'").trim().replace(/\s+/g,' ').replace(/^[^a-z]+|[^a-z]+$/g,'');
 if(!key)return {key:'',entry:null,lemma:''};
 const forms=[key];
 if(key.endsWith("'s"))forms.push(key.slice(0,-2));
 if(key.endsWith('ies'))forms.push(key.slice(0,-3)+'y');
 if(key.endsWith('ing')){const stem=key.slice(0,-3);forms.push(stem,stem+'e',stem.slice(0,-1));}
 if(key.endsWith('ed')){const stem=key.slice(0,-2);forms.push(stem,stem+'e',stem.slice(0,-1));}
 if(key.endsWith('es'))forms.push(key.slice(0,-2));
 if(key.endsWith('s'))forms.push(key.slice(0,-1));
 const form=forms.find(hasTerm),direct=form?dictionary[form]:null,lemma=direct?.[2]&&hasTerm(direct[2])?direct[2]:form&&form!==key?form:'';
 const entry=lemma&&hasTerm(lemma)?dictionary[lemma]:direct;
 return {key,entry,lemma,pronunciation:entry?.[0]||direct?.[0]||''};
}
function contextSense(entry,context){
 if(!entry||!context)return '';
 const chinese=translation(context)[0];
 for(const sense of entry[1])for(const part of sense.split(/[,，；;、]/)){
  const phrase=part.replace(/^[a-z.\[\]()\s]+/i,'').trim();
  if(phrase.length>=2&&phrase.length<=8&&chinese.includes(phrase))return phrase;
 }
 return '';
}
function showWord(raw,context=null){
 const dialog=$('#wordDialog'),result=lookupTerm(raw),entry=result.entry;
 if(!dialog.open){wordReturnFocus=document.activeElement;if(active){stop();status('查词已暂停，关闭后点继续。');}}
 $('#wordTitle').textContent=raw.trim()||'查词';$('#wordSearch').value=raw.trim();
 $('#wordPhonetic').textContent=result.pronunciation?`/${result.pronunciation}/`:'';
 $('#wordLemma').textContent=result.lemma&&result.lemma!==result.key?`原形 / 查询词：${result.lemma}`:'';
 const matched=contextSense(entry,context);$('#wordContextSense').hidden=!matched;$('#wordContextSense').textContent=matched?`本句译文中对应的词义线索：${matched}（自动匹配）`:'';
 $('#wordMeanings').innerHTML=entry?`<strong>常见词义</strong><ul>${entry[1].map(sense=>`<li>${esc(sense)}</li>`).join('')}</ul>`:'<p class="dictMissing">这项尚未收录在离线词典；可尝试查询原形或缩短短语。</p>';
 $('#wordContext').hidden=!context;
 if(context){$('#wordContextEnglish').textContent=context.text;$('#wordContextChinese').textContent=translation(context)[0];}
 if(!dialog.open){dialog.showModal();$('#wordClose').focus({preventScroll:true});}
}
$('#wordClose').onclick=()=>$('#wordDialog').close();
$('#wordSearchForm').onsubmit=e=>{e.preventDefault();showWord($('#wordSearch').value);};
$('#wordDialog').addEventListener('close',()=>{if(wordReturnFocus?.isConnected)wordReturnFocus.focus({preventScroll:true});wordReturnFocus=null;});
$('#wordDialog').addEventListener('click',e=>{if(e.target===$('#wordDialog'))$('#wordDialog').close();});
function fillRange(){$('#rangeStart').value=rangeStart+1;$('#rangeEnd').value=rangeEnd+1;$('#rangeStart').max=$('#rangeEnd').max=lesson.cues.length;$('#autoNext').checked=auto;$('#screenRepeats').value=screenRepeats;$('#loopRange').checked=loop;$('#rangeSummary').textContent=auto?`自动切换 · 每句 ${screenRepeats} 遍 · ${rangeStart+1}–${rangeEnd+1} · ${loop?'区间循环':'末尾停止'}`:`手动切换 · 当前句循环 · ${rangeStart+1}–${rangeEnd+1}`;}
function openScreen(i=index){returnFocus=document.activeElement;bodyScroll=scrollY;index=i;screen=true;locked=false;$('#screen').hidden=false;$('#screen').append($('#wordDialog'));$('#screen').classList.remove('locked');$('#lock').textContent='锁定';$('#lock').setAttribute('aria-pressed','false');$('#app').inert=$('#playerBar').inert=true;document.body.classList.add('screenOpen');$('#screenPlayback').open=false;renderScreen();fillRange();$('#screenCard').focus();play();
 if(!prefs.intro){prefs.intro=true;save();$('#swipeIntro').hidden=false;introTimer=setTimeout(()=>$('#swipeIntro').hidden=true,1500);}
 if($('#screen').requestFullscreen)$('#screen').requestFullscreen().then(()=>{if(!screen&&document.fullscreenElement===$('#screen'))document.exitFullscreen().catch(()=>{});}).catch(()=>{});
}
function closeScreen(){if(locked)return;if($('#wordDialog').open)$('#wordDialog').close();stop();screen=false;clearTimeout(introTimer);$('#swipeIntro').hidden=true;$('#screen').hidden=true;document.body.append($('#wordDialog'));$('#app').inert=$('#playerBar').inert=false;document.body.classList.remove('screenOpen');if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});window.scrollTo(0,bodyScroll);returnFocus?.isConnected&&returnFocus.focus();}
function lock(){locked=!locked;$('#screen').classList.toggle('locked',locked);$('#lock').textContent=locked?'解锁':'锁定';$('#lock').setAttribute('aria-pressed',String(locked));$('#lockHint').textContent=locked?'已锁定 · 仅可上下滑动 · 点击右上角解锁':'上下滑切换 · 点英文单词查义 · 空格暂停 · Esc 退出';for(const el of document.querySelectorAll('.screenSettings,.screenCourseLabel,#exitScreen,.screenBottom label,.two,#screenHero button'))el.inert=locked;$('#screenCard').focus();}
$('#books').onclick=e=>{const b=e.target.closest('[data-book]');if(b)choose(data.find(l=>l.book===Number(b.dataset.book)));};
$('#lessons').onclick=e=>{const el=e.target.closest('[data-lesson]');if(el){choose(data.find(l=>l.id===el.dataset.lesson));$('#lessonPicker').open=false;$('#lessonPicker summary').focus({preventScroll:true});}};
$('#search').oninput=()=>{renderLessons();$('#lessonPicker').open=true;};$('#onlyFavorites').onchange=()=>{renderLessons();$('#lessonPicker').open=true;};
$('#clearSearch').onclick=()=>{$('#search').value='';renderLessons();$('#search').focus();};
$('#mobileSettingsBtn').onclick=()=>{const open=document.body.classList.toggle('mobile-settings-open');$('#mobileSettingsBtn').setAttribute('aria-expanded',String(open));};
$('#transcript').onclick=e=>{const word=e.target.closest('.wordToken,.phraseToken');if(word){const row=word.closest('[data-cue]');if(row)showWord(word.dataset.word,lesson.cues[Number(row.dataset.cue)]);return;}const b=e.target.closest('[data-action]'),row=b?.closest('[data-cue]');if(!b||!row)return;const i=Number(row.dataset.cue),c=lesson.cues[i];if(b.dataset.action==='favorite')return mark(favorites,c.id);if(b.dataset.action==='mastered')return mark(mastered,c.id);if(b.dataset.action==='timing'){editing=c;$('#timingText').textContent=c.text;$('#timingStart').value=bounds(c).start;$('#timingEnd').value=bounds(c).end;$('#timingError').textContent='';$('#timingDialog').showModal();return;}index=i;renderCurrent();if(b.dataset.action==='screen')openScreen(i);else play();};
$('#screenHero').onclick=e=>{const word=e.target.closest('.wordToken,.phraseToken');if(word&&!locked)showWord(word.dataset.word,cue());};
$('#playLesson').onclick=()=>play('lesson');$('#playCues').onclick=()=>play();$('#pause').onclick=togglePlay;$('#screenPause').onclick=togglePlay;
for(const [id,delta] of [['previousCue',-1],['nextCue',1]])$('#'+id).onclick=()=>{if(index+delta<0||index+delta>=lesson.cues.length)return;stop();index+=delta;completed=0;renderCurrent();play();};
$('#openScreen').onclick=()=>openScreen();$('#exitScreen').onclick=closeScreen;$('#lock').onclick=lock;
$('#screenLessonSelect').onchange=e=>{const next=data.find(l=>l.id===e.target.value);if(next){choose(next);fillRange();play();}};
$('#playCues').insertAdjacentHTML('beforebegin','<label>发音来源 <select id="voiceMode" aria-label="发音来源"></select></label><span id="voiceNotice"></span>');
const voiceOptions='<option value="original">原版课文录音</option>'+voiceData.voices.map(v=>`<option value="${v.id}" ${voiceData.ready?'':'disabled'}>${esc(v.label)}</option>`).join('')+(voiceData.ready?'<option value="gb-cycle">↻ 三种英音交替</option><option value="us-cycle">↻ 三种美音交替</option><option value="all-cycle">↻ 六种英美音色交替</option>':'');
for(const id of ['voiceMode','screenVoice']){$('#'+id).innerHTML=voiceOptions;$('#'+id).value=prefs.voice;$('#'+id).onchange=e=>{const wasPlaying=active;stop();prefs.voice=voiceModes.has(e.target.value)?e.target.value:'original';voiceTurn=0;for(const key of ['voiceMode','screenVoice'])$('#'+key).value=prefs.voice;save();if(wasPlaying)play();else status('已切换音色，点播放开始。');};}
$('#voiceNotice').textContent=voiceData.ready?'六种内置音色为合成发音；整课播放始终使用原版录音。':'六音色资源尚未就绪，原版录音仍可使用。';
$('#reveal').onclick=()=>{$('#screenText').hidden=false;$('#screenPhrases').hidden=!$('#screenPhrases').innerHTML;$('#reveal').hidden=true;};
$('#translationReveal').onclick=()=>{$('#screenTranslation').hidden=false;$('#translationReveal').hidden=true;renderContext();};
$('#screenFavorite').onclick=()=>mark(favorites,cue().id);$('#screenMastered').onclick=()=>mark(mastered,cue().id);
$('#detailsToggle').onclick=()=>{details=!details;renderContext();};
$('#screenForm').onsubmit=e=>{e.preventDefault();const a=Number($('#rangeStart').value),b=Number($('#rangeEnd').value),r=Number($('#screenRepeats').value);if(![a,b,r].every(Number.isInteger)||a<1||b>lesson.cues.length||a>b||r<1||r>100){$('#rangeError').textContent='请输入有效的课内句子区间和 1–100 遍次数。';return;}rangeStart=a-1;rangeEnd=b-1;screenRepeats=r;auto=$('#autoNext').checked;loop=$('#loopRange').checked;index=rangeStart;$('#rangeError').textContent='';fillRange();$('#screenPlayback').open=false;renderCurrent();play();};
for(const id of ['speed','barSpeed','screenSpeed']){$('#'+id).innerHTML=Array.from({length:31},(_,i)=>{const v=((50+5*i)/100).toFixed(2);return `<option value="${v}">${v}×</option>`;}).join('');$('#'+id).value=prefs.speed.toFixed(2);$('#'+id).onchange=e=>{prefs.speed=Number(e.target.value);audio.playbackRate=audio.defaultPlaybackRate=prefs.speed;for(const key of ['speed','barSpeed','screenSpeed'])$('#'+key).value=prefs.speed.toFixed(2);save();};}
$('#gap').value=String(prefs.gap);$('#gap').onchange=e=>{prefs.gap=Number(e.target.value);save();};$('#repeat').value=String(prefs.repeat);$('#repeat').onchange=e=>{prefs.repeat=Number(e.target.value);save();};
function applyDisplay(){document.body.classList.toggle('dark',prefs.theme==='dark');$('#themeColorMeta').content=prefs.theme==='dark'?'#111111':'#f7f7f7';$('#theme').textContent=prefs.theme==='dark'?'◐ 浅色':'◐ 深色';$('#screen').style.setProperty('--font',prefs.font/100);$('#screen').style.setProperty('--translation-font',prefs.translationFont/100);$('#screen').style.setProperty('--context-font',prefs.contextFont/100);$('#fontSize').value=prefs.font;$('#fontValue').textContent=prefs.font+'%';$('#translationFontSize').value=prefs.translationFont;$('#translationFontValue').textContent=prefs.translationFont+'%';$('#contextFontSize').value=prefs.contextFont;$('#contextFontValue').textContent=prefs.contextFont+'%';$('#hideText').checked=!!prefs.hide;$('#hideTranslation').checked=!!prefs.hideTranslation;$('#showTranslations').checked=!!prefs.showTranslations;$('#defaultDetails').checked=!!prefs.details;}
$('#theme').onclick=()=>{prefs.theme=prefs.theme==='dark'?'light':'dark';applyDisplay();save();};$('#fontSize').oninput=e=>{prefs.font=Number(e.target.value);applyDisplay();save();};$('#hideText').onchange=e=>{prefs.hide=e.target.checked;renderScreen();save();};$('#defaultDetails').onchange=e=>{prefs.details=e.target.checked;details=prefs.details;renderContext();save();};
$('#translationFontSize').oninput=e=>{prefs.translationFont=Number(e.target.value);applyDisplay();save();};$('#contextFontSize').oninput=e=>{prefs.contextFont=Number(e.target.value);applyDisplay();save();};$('#fontReset').onclick=()=>{prefs.font=prefs.translationFont=prefs.contextFont=100;applyDisplay();save();};
$('#showTranslations').onchange=e=>{prefs.showTranslations=e.target.checked;document.querySelectorAll('.cueZh').forEach(el=>el.hidden=!prefs.showTranslations);save();};
$('#hideTranslation').onchange=e=>{prefs.hideTranslation=e.target.checked;$('#screenTranslation').hidden=!!prefs.hideTranslation;$('#translationReveal').hidden=!prefs.hideTranslation;renderContext();save();};
audio.ontimeupdate=()=>{const duration=playingAsset?playingAsset.duration:lesson.duration;$('#seek').max=duration;$('#seek').value=audio.currentTime;$('#clock').textContent=`${time(audio.currentTime)} / ${time(duration)}`;if(mode==='lesson'&&active){const i=lesson.cues.findIndex(c=>audio.currentTime>=bounds(c).start&&audio.currentTime<bounds(c).end);if(i>=0&&i!==index){index=i;renderCurrent();}}};
$('#seek').oninput=e=>{const position=Number(e.target.value);if(audio.src!==new URL(lesson.audio,location.href).href)return;stop();mode='lesson';audio.currentTime=position;status('已定位，点击整课播放将从头开始。');};
$('#timingForm').onsubmit=e=>{e.preventDefault();const start=Number($('#timingStart').value),end=Number($('#timingEnd').value);if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>lesson.duration){$('#timingError').textContent=`需满足 0 ≤ 开始 < 结束 ≤ ${lesson.duration} 秒。`;return;}corrections[editing.id]={start,end};save();stop();renderTranscript();$('#timingDialog').close();};$('#closeTiming').onclick=()=>$('#timingDialog').close();$('#resetTiming').onclick=()=>{delete corrections[editing.id];save();stop();renderTranscript();$('#timingDialog').close();};
for(const type of ['click','input','change','submit'])$('#screen').addEventListener(type,e=>{if(locked&&!e.target.closest('#lock')){e.preventDefault();e.stopImmediatePropagation();}},true);
$('#screenCard').addEventListener('touchstart',e=>{if(e.touches.length!==1||e.target.closest('button:not(.wordToken)')){gesture=null;return;}const scroll=e.target.closest('#screenContext,#screenHero');gesture={x:e.touches[0].clientX,y:e.touches[0].clientY,scroll,top:scroll?.scrollTop||0,dy:0,kind:null};},{passive:true});
$('#screenCard').addEventListener('touchmove',e=>{if(!gesture||e.touches.length!==1)return;const g=gesture,dx=e.touches[0].clientX-g.x,dy=e.touches[0].clientY-g.y;g.dy=dy;if(!g.kind&&Math.max(Math.abs(dx),Math.abs(dy))>10){const can=g.scroll&&(dy<0?g.top+g.scroll.clientHeight<g.scroll.scrollHeight-2:g.top>0);g.kind=Math.abs(dx)>Math.abs(dy)?'ignore':!locked&&can?'scroll':'swipe';}if(g.kind==='scroll'){e.preventDefault();g.scroll.scrollTop=g.top-dy;}if(g.kind==='swipe')e.preventDefault();},{passive:false});
$('#screenCard').addEventListener('touchend',()=>{const g=gesture;gesture=null;if(g?.kind==='swipe'&&Math.abs(g.dy)>55)step(g.dy<0?1:-1);});$('#screenCard').addEventListener('touchcancel',()=>gesture=null);
let wheelAt=0;$('#screenCard').addEventListener('wheel',e=>{if(e.ctrlKey||Math.abs(e.deltaX)>Math.abs(e.deltaY))return;const el=e.target.closest('#screenContext,#screenHero');if(!locked&&el&&(e.deltaY>0?el.scrollTop+el.clientHeight<el.scrollHeight-2:el.scrollTop>0))return;e.preventDefault();if(Date.now()-wheelAt>350&&Math.abs(e.deltaY)>25){wheelAt=Date.now();step(e.deltaY>0?1:-1);}},{passive:false});
document.addEventListener('keydown',e=>{if(!screen||$('#timingDialog').open||$('#wordDialog').open)return;if(locked){if(e.key==='Tab'){e.preventDefault();$('#lock').focus();}else if(!(e.target===$('#lock')&&[' ','Enter'].includes(e.key)))e.preventDefault();return;}if(e.key==='Escape'){e.preventDefault();closeScreen();return;}if(e.key==='Tab'){const els=[...$('#screen').querySelectorAll('button,input,select,summary,[tabindex="0"]')].filter(el=>!el.disabled&&el.getClientRects().length);if(e.shiftKey&&document.activeElement===els[0]){e.preventDefault();els.at(-1).focus();}else if(!e.shiftKey&&document.activeElement===els.at(-1)){e.preventDefault();els[0].focus();}return;}if(e.target.closest('input,select,summary,button'))return;if(e.key==='ArrowDown'){e.preventDefault();step(1);}if(e.key==='ArrowUp'){e.preventDefault();step(-1);}if(e.code==='Space'){e.preventDefault();togglePlay();}},true);
document.addEventListener('visibilitychange',()=>{if(document.hidden&&active){stop();status('切到后台已暂停，请点继续。');}});
$('#exportProgress').onclick=()=>{save();const url=URL.createObjectURL(new Blob([JSON.stringify({version:1,...prefs},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='nce-learning-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('#importProgress').onchange=async e=>{try{const f=e.target.files[0];if(!f||f.size>5e6)throw Error();const p=JSON.parse(await f.text());if(p.version!==1||!Array.isArray(p.favorites)||!Array.isArray(p.mastered))throw Error();favorites.clear();mastered.clear();migrateMarks(p.favorites).forEach(id=>favorites.add(id));migrateMarks(p.mastered).forEach(id=>mastered.add(id));corrections={};for(const [id,b] of Object.entries(p.corrections||{})){if((validIds.has(id)||sourceParts.has(id))&&Number.isFinite(b?.start)&&Number.isFinite(b?.end)&&b.start>=0&&b.end>b.start)corrections[id]=b;}save();render();$('#backupStatus').textContent='已恢复收藏、掌握记录与时间校准；旧整句校准保留在备份中，不会错误套用到拆分片段。';}catch{$('#backupStatus').textContent='备份无效，请选择本项目导出的 JSON 文件。';}};
// Download only the selected sentence range and selected accent pack.
let voiceDownloadPort=null,voiceDownloadTimer=null;
function voiceDownloadBusy(busy){for(const id of ['voiceDownloadStart','voiceDownloadEnd','voiceDownloadPack','voiceDownloadRange'])$('#'+id).disabled=busy;$('#voiceDownload').disabled=busy||!voiceData.ready;$('#voiceDownloadCancel').hidden=!busy;}
function finishVoiceDownload(message){clearTimeout(voiceDownloadTimer);voiceDownloadPort?.close();voiceDownloadPort=null;voiceDownloadBusy(false);$('#voiceDownloadStatus').textContent=message;}
voiceDownloadBusy(false);
$('#voiceDownloadRange').onclick=()=>{$('#voiceDownloadStart').value=rangeStart+1;$('#voiceDownloadEnd').value=rangeEnd+1;};
$('#voiceDownloadCancel').onclick=()=>voiceDownloadPort?.postMessage('cancel');
$('#voiceDownloadForm').onsubmit=e=>{
 e.preventDefault();if(voiceDownloadPort)return;
 const a=Number($('#voiceDownloadStart').value),b=Number($('#voiceDownloadEnd').value),pack=$('#voiceDownloadPack').value;
 if(!Number.isInteger(a)||!Number.isInteger(b)||a<1||a>b||b>lesson.cues.length){$('#voiceDownloadStatus').textContent='请输入有效的本课条目区间。';return;}
 if(!voiceData.ready){$('#voiceDownloadStatus').textContent='六音色资源尚未生成完整。';return;}
 if(!navigator.serviceWorker?.controller){$('#voiceDownloadStatus').textContent='首次打开请等待缓存就绪后刷新；离线下载需要 HTTPS。';return;}
 const voices=voiceData.voices.filter(v=>pack==='all'||v.id.startsWith(pack+'-')).map(v=>v.id),ids=lesson.cues.slice(a-1,b).map(c=>c.id);
 const total=new Set(ids.flatMap(id=>voices.map(v=>`${v}/${voiceData.cues[id]}`))).size;
 const title=`Lesson ${lesson.number} · ${a}–${b}`,channel=new MessageChannel();voiceDownloadPort=channel.port1;
 voiceDownloadBusy(true);$('#voiceDownloadProgress').hidden=false;$('#voiceDownloadProgress').max=total;$('#voiceDownloadProgress').value=0;
 const watch=()=>{clearTimeout(voiceDownloadTimer);voiceDownloadTimer=setTimeout(()=>{voiceDownloadPort?.postMessage('cancel');finishVoiceDownload('下载中断，已下载部分保留，可重试补齐。');},90000);};
 voiceDownloadPort.onmessage=({data:m})=>{watch();$('#voiceDownloadProgress').value=m.loaded||0;const counts=`${m.loaded||0}/${total} 个音频`;if(m.done||m.error||m.cancelled)finishVoiceDownload(m.error||`${m.cancelled?'已取消':'下载完成'} · ${title} · ${counts}，已下载部分保留。`);else $('#voiceDownloadStatus').textContent=`${title} · ${counts} 已就绪`;};
 watch();navigator.serviceWorker.controller.postMessage({type:'DOWNLOAD_TTS',ids,voices},[channel.port2]);
};
window.addEventListener('pagehide',()=>{if(voiceDownloadPort){voiceDownloadPort.postMessage('cancel');finishVoiceDownload('离开页面后下载已中断，可重试补齐。');}});
// Download whole source lessons so all sentence ranges share one cached recording.
let downloadPort=null,downloadTimer=null;
function fillDownloads(){if(downloadPort)return;const lessons=data.filter(l=>l.book===book);const html=lessons.map(l=>`<option value="${l.id}">Lesson ${l.number}</option>`).join('');$('#downloadStart').innerHTML=$('#downloadEnd').innerHTML=html;const id=lessons.some(l=>l.id===lesson.id)?lesson.id:lessons[0].id;$('#downloadStart').value=$('#downloadEnd').value=id;estimate();}
function selectedDownloads(){const list=data.filter(l=>l.book===book),a=list.findIndex(l=>l.id===$('#downloadStart').value),b=list.findIndex(l=>l.id===$('#downloadEnd').value);return a<0||b<a?[]:list.slice(a,b+1);}
function estimate(){const list=selectedDownloads();$('#downloadEstimate').textContent=list.length?`${list.length} 课 · 原声音频约 ${(list.reduce((n,l)=>n+l.bytes,0)/1048576).toFixed(1)} MB（已缓存的不会重复下载）`:'结束课不能早于起始课。';}
$('#downloadStart').onchange=$('#downloadEnd').onchange=estimate;
function endDownload(text){clearTimeout(downloadTimer);downloadPort?.close();downloadPort=null;for(const id of ['downloadStart','downloadEnd','download'])$('#'+id).disabled=false;$('#cancelDownload').hidden=true;$('#downloadStatus').textContent=text;if(data.find(l=>l.id===$('#downloadStart').value)?.book!==book)fillDownloads();}
$('#downloadForm').onsubmit=e=>{e.preventDefault();if(downloadPort)return;const lessons=selectedDownloads();if(!lessons.length){$('#downloadStatus').textContent='请选择有效课程区间。';return;}if(!navigator.serviceWorker?.controller){$('#downloadStatus').textContent='离线下载需要 HTTPS 网页及缓存支持；首次打开请等待缓存就绪后刷新。';return;}const channel=new MessageChannel();downloadPort=channel.port1;for(const id of ['downloadStart','downloadEnd','download'])$('#'+id).disabled=true;$('#cancelDownload').hidden=false;$('#downloadProgress').hidden=false;$('#downloadProgress').max=lessons.length;$('#downloadProgress').value=0;const watch=()=>{clearTimeout(downloadTimer);downloadTimer=setTimeout(()=>{downloadPort?.postMessage('cancel');endDownload('下载中断，可重试补齐已有缓存。');},90000);};watch();downloadPort.onmessage=({data:m})=>{watch();$('#downloadProgress').value=m.loaded||0;const text=`${m.loaded||0}/${lessons.length} 课已缓存`;if(m.done||m.error||m.cancelled)endDownload(m.error||`${m.cancelled?'已取消':'下载完成'} · ${text}，已下载部分保留。`);else $('#downloadStatus').textContent=text;};navigator.serviceWorker.controller.postMessage({type:'DOWNLOAD',ids:lessons.map(l=>l.id)},[channel.port2]);};
$('#cancelDownload').onclick=()=>downloadPort?.postMessage('cancel');window.addEventListener('pagehide',()=>{stop();downloadPort?.postMessage('cancel');if(downloadPort)endDownload('离开页面后下载已中断，可重试补齐。');});
const audioPrefix=new URL('audio/',location.href).pathname,originalBytes=new Map(data.map(l=>[l.audio.replace(/^audio\//,''),l.bytes]));
const megabytes=bytes=>`${(bytes/1048576).toFixed(1)} MB`;
function cacheAsset(request){
 const path=new URL(request.url).pathname;if(!path.startsWith(audioPrefix))return null;
 const relative=path.slice(audioPrefix.length),source=originalBytes.get(relative);
 if(source!==undefined)return {kind:'original',bytes:source,book:Number(relative[1]),lesson:relative};
 const match=/^tts\/([^/]+)\/([^/]+)\.m4a$/.exec(relative);if(!match)return null;
 const meta=voiceData.assets[`${match[1]}/${match[2]}`];
 return meta?{kind:'tts',bytes:meta[0],voice:match[1],key:match[2]}:null;
}
async function cachedAudio(){const cache=await caches.open('nce-audio-v1');const items=[];for(const request of await cache.keys()){const asset=cacheAsset(request);if(asset)items.push({request,...asset});}return {cache,items};}
async function refreshCache(){
 $('#refreshCache').disabled=true;$('#cacheUsage').textContent='正在统计离线音频…';
 try{const {items}=await cachedAudio(),original=items.filter(a=>a.kind==='original'),voices=items.filter(a=>a.kind==='tts');
  const sum=rows=>rows.reduce((n,a)=>n+a.bytes,0);
  let text=`原声 ${original.length} 课 · ${megabytes(sum(original))}；合成音色 ${voices.length} 个 · ${megabytes(sum(voices))}。`;
  if(navigator.storage?.estimate){const estimate=await navigator.storage.estimate();if(estimate.usage&&estimate.quota)text+=` 浏览器总占用约 ${megabytes(estimate.usage)} / 配额 ${megabytes(estimate.quota)}。`;}
  $('#cacheUsage').textContent=text;
 }catch{$('#cacheUsage').textContent='无法读取缓存统计；可能是浏览器未开放离线存储。';}
 finally{$('#refreshCache').disabled=false;}
}
$('#refreshCache').onclick=refreshCache;
$('#clearCache').onclick=async()=>{
 if(downloadPort||voiceDownloadPort){$('#cacheStatus').textContent='请先结束正在进行的下载，再清理缓存。';return;}
 const scope=$('#cacheScope').value,selected=new Set(selectedDownloads().map(l=>l.audio.replace(/^audio\//,'')));
 const currentKeys=new Set(lesson.cues.map(c=>voiceData.cues[c.id]));
 let cache,items;try{({cache,items}=await cachedAudio());}
 catch{$('#cacheStatus').textContent='无法读取音频缓存；请确认使用 HTTPS 或 localhost，并允许此站点离线存储。';return;}
 const targets=items.filter(a=>scope==='original-range'?a.kind==='original'&&selected.has(a.lesson):scope==='original-book'?a.kind==='original'&&a.book===book:scope==='tts-lesson'?a.kind==='tts'&&currentKeys.has(a.key):scope==='tts-gb'?a.kind==='tts'&&a.voice.startsWith('gb-'):scope==='tts-us'?a.kind==='tts'&&a.voice.startsWith('us-'):a.kind==='tts');
 if(!targets.length){$('#cacheStatus').textContent='选中范围没有已缓存的音频。';return;}
 const size=targets.reduce((n,a)=>n+a.bytes,0);
 if(!confirm(`确定清理 ${targets.length} 个音频（约 ${megabytes(size)}）？清理后需要联网才能重新播放或下载；学习记录不会删除。`))return;
 $('#clearCache').disabled=true;$('#cacheStatus').textContent=`正在清理 ${targets.length} 个音频…`;stop();
 let removed=0;try{for(const item of targets)if(await cache.delete(item.request))removed++;$('#cacheStatus').textContent=`已清理 ${removed} 个音频。学习记录和网页离线文件保留。`;await refreshCache();}
 catch{$('#cacheStatus').textContent=`清理中断，已移除 ${removed} 个音频；可重试。`;}
 finally{$('#clearCache').disabled=false;}
};
$('#totals').textContent=`4 册 · ${data.length} 课 · ${data.reduce((n,l)=>n+l.cues.length,0).toLocaleString()} 句／片段 · 英文原文与原声录音`;
applyDisplay();render();if('serviceWorker'in navigator&&/^https?:$/.test(location.protocol))navigator.serviceWorker.register('./sw.js').catch(()=>{});
})();
