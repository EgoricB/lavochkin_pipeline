import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from getpass import getpass

HTML = r"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Каталог NTRS</title>
<style>body{font:16px system-ui;max-width:1050px;margin:30px auto;padding:15px}input,select,button{padding:8px;margin:5px;max-width:95%}article{padding:15px 0;border-bottom:1px solid #ddd}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#175ab5}</style>
<a href="../">← Атлас</a><h1>Каталог NASA NTRS</h1><p id="status">Загрузка…</p>
<p>Статический снимок PostgreSQL. Поиск по названию, аннотации и ID. Полные тексты и PDF в эту публикацию не включены.</p>
<div id="catalog"><form id="form"><input id="q" placeholder="Поиск"><select id="topic"><option value="">Все темы</option></select><label>Минимальный вес <input id="weight" type="number" min="0" max="1" step="0.01" value="0.2"></label><select id="text"><option value="">Все документы</option><option value="yes">С текстом в БД</option><option value="no">Без текста в БД</option></select><button>Найти</button></form><p id="count"></p><button id="csv">Экспорт подборки CSV</button><div id="results"></div><button id="prev">Назад</button><span id="page"></span><button id="next">Вперёд</button></div><div id="card" hidden></div>
<script>
'use strict';const $=id=>document.getElementById(id);let data,found=[],page=1;
function el(tag,text,parent){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(parent)parent.append(e);return e}
function a(parent,text,url){const e=el('a',text,parent);e.href=url;return e}
function filter(){const q=$('q').value.trim().toLowerCase(),t=$('topic').value,w=Number($('weight').value),h=$('text').value;if(!Number.isFinite(w)||w<0||w>1){alert('Вес: от 0 до 1');return}found=data.documents.filter(d=>(!q||[d.id,d.title,d.abstract].join(' ').toLowerCase().includes(q))&&(t===''||(d.weights&&d.weights[Number(t)]>=w))&&(!h||d.has_text===(h==='yes')));page=1;render()}
function render(){$('results').replaceChildren();const pages=Math.max(1,Math.ceil(found.length/25));page=Math.min(page,pages);$('count').textContent='Найдено: '+found.length;$('page').textContent=` ${page} / ${pages} `;$('prev').disabled=page<=1;$('next').disabled=page>=pages;for(const d of found.slice((page-1)*25,page*25)){const box=el('article',undefined,$('results'));a(box,d.title||d.id,'#doc='+encodeURIComponent(d.id));el('p','NTRS '+d.id+' · '+(d.has_text?'есть текст в БД':'нет текста в БД'),box);el('p',d.abstract.slice(0,350),box)}}
function route(){const id=new URLSearchParams(location.hash.slice(1)).get('doc');$('catalog').hidden=!!id;$('card').hidden=!id;const c=$('card');c.replaceChildren();if(!id)return;const d=data.documents.find(x=>x.id===id);if(!d){el('p','Не найдено',c);return}a(c,'← К подборке','#');el('h2',d.title||d.id,c);el('p','NTRS ID: '+d.id,c);if(/^\d+$/.test(d.id)){const link=a(c,'Источник NASA NTRS','https://ntrs.nasa.gov/citations/'+encodeURIComponent(d.id));link.target='_blank';link.rel='noopener noreferrer'}el('p','Тип: '+(d.type||'не указан'),c);el('h3','Аннотация',c);el('pre',d.abstract||'Нет аннотации',c);el('h3','Тематический профиль',c);el('p','Относительные модельные веса; не проценты содержания.',c);if(d.weights){for(const t of data.topics)el('p',(t.label||'Тема '+t.number)+': '+d.weights[t.number].toFixed(6)+' · '+t.terms.slice(0,8).join(', '),c)}else el('p','Тематический профиль отсутствует',c);el('h3','Происхождение',c);el('p','Модель: '+data.model,c);el('p','SHA-256 исходной канонической записи: '+d.record_sha256,c);el('p',d.normalized?'NUL нормализован при импорте; оригинал сохранён в рабочей БД.':'Нормализация NUL не применялась.',c);el('p','Полные тексты и PDF доступны через источник, если предоставлены им. Миссионная разметка ещё не добавлена.',c)}
function cell(v){let s=String(v??'');if(/^[\s]*[=+\-@]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"'}
$('csv').onclick=()=>{const filters=JSON.stringify({q:$('q').value,topic:$('topic').value,weight:$('weight').value,text:$('text').value});const rows=[['ntrs_id','title','abstract','document_type','has_text','model','built_at','filters',...data.topics.map(t=>'topic_'+t.number)],...found.map(d=>[d.id,d.title,d.abstract,d.type,d.has_text,data.model,data.built_at,filters,...data.topics.map(t=>d.weights?d.weights[t.number]:'')])];const b=new Blob(['\ufeff'+rows.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});const u=URL.createObjectURL(b);const link=a(document.body,'',u);link.download='ntrs-selection.csv';link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(u),1000)};
$('form').onsubmit=e=>{e.preventDefault();filter()};$('prev').onclick=()=>{page--;render()};$('next').onclick=()=>{page++;render()};window.addEventListener('hashchange',()=>{if(data)route()});
fetch('./catalog-data.json').then(r=>{if(!r.ok)throw Error(r.status);return r.json()}).then(d=>{data=d;$('status').textContent=`Документов: ${d.documents.length}; тем: ${d.topics.length}; сборка: ${d.built_at}`;for(const t of d.topics){const o=el('option',t.label||`Тема ${t.number}: ${t.terms.slice(0,4).join(', ')}`,$('topic'));o.value=t.number}filter();route()}).catch(()=>{$('status').textContent='Ошибка загрузки. Откройте каталог через HTTP, не как файл.'});
</script></html>"""


def main():
    import psycopg
    from psycopg.rows import dict_row
    p=argparse.ArgumentParser(description='Export a read-only static catalogue to docs/catalog')
    p.add_argument('--output',type=Path,default=Path('docs/catalog'))
    p.add_argument('--model-key')
    args=p.parse_args()
    target=args.output
    if target.exists():
        raise SystemExit('Output directory already exists. Nothing changed.')
    with psycopg.connect(host='127.0.0.1',port=5432,dbname='lavochkin_catalog',user='lavochkin_app',password=getpass('Password for lavochkin_app: '),connect_timeout=10,row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        if args.model_key:
            model=conn.execute('SELECT * FROM catalog.topic_models WHERE model_key=%s',(args.model_key,)).fetchone()
        else:
            model=conn.execute('SELECT * FROM catalog.topic_models ORDER BY id DESC LIMIT 1').fetchone()
        if model is None:raise ValueError('No topic model')
        topics=conn.execute('SELECT topic_number,label,top_terms FROM catalog.topics WHERE model_id=%s ORDER BY topic_number',(model['id'],)).fetchall()
        if [t['topic_number'] for t in topics]!=list(range(model['topic_count'])):raise ValueError('Incomplete topic list')
        rows=conn.execute("SELECT d.ntrs_id,d.title,d.abstract,d.document_type,v.has_nonempty_text,v.record_sha256,coalesce(v.source_record ? '_catalog_import',false) AS normalized FROM catalog.documents d LEFT JOIN catalog.document_current_versions cv ON cv.document_id=d.id LEFT JOIN catalog.document_versions v ON v.id=cv.version_id ORDER BY d.ntrs_id").fetchall()
        cells=conn.execute('SELECT d.ntrs_id,t.topic_number,dt.relative_weight FROM catalog.document_topics dt JOIN catalog.documents d ON d.id=dt.document_id JOIN catalog.topics t ON t.id=dt.topic_id WHERE t.model_id=%s',(model['id'],)).fetchall()
        weights={}
        for c in cells:weights.setdefault(c['ntrs_id'],{})[c['topic_number']]=c['relative_weight']
        for ident,profile in weights.items():
            if set(profile)!=set(range(len(topics))) or abs(sum(profile.values())-1)>1e-8:raise ValueError('Invalid profile: '+ident)
        data={'built_at':datetime.now(timezone.utc).isoformat(),'model':model['model_key'],'topics':[{'number':t['topic_number'],'label':t['label'],'terms':t['top_terms']} for t in topics],'documents':[{'id':r['ntrs_id'],'title':r['title'],'abstract':r['abstract'],'type':r['document_type'],'has_text':bool(r['has_nonempty_text']),'record_sha256':r['record_sha256'],'normalized':r['normalized'],'weights':[weights[r['ntrs_id']][i] for i in range(len(topics))] if r['ntrs_id'] in weights else None} for r in rows]}
    raw=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    manifest={'builder':'build_pages_catalog.py','built_at':data['built_at'],'documents':len(rows),'topics':len(topics),'profile_documents':len(weights),'data_bytes':len(raw),'data_sha256':hashlib.sha256(raw).hexdigest(),'full_text_published':False}
    target.mkdir(parents=True,exist_ok=False)
    (target/'catalog-data.json').write_bytes(raw)
    (target/'index.html').write_text(HTML,encoding='utf-8')
    (target/'catalog-build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    main()
