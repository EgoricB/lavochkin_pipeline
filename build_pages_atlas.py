import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
CORPUS = ROOT / "data/ntrs/research/corpus_v2/documents.jsonl"
RESULTS = DOCS / "research/ntrs-topic-analysis/artifacts"
TARGET = DOCS / "index.html"
LABELS = [
    "Космические программы и технологии", "Езеро и Perseverance",
    "Атмосфера Венеры", "Каталоги космических данных",
    "Лунные исследования", "Фобос и Деймос",
    "Транспортные архитектуры", "Плазма и магнитные поля",
    "Геология и картографирование Венеры", "Вход в атмосферу и тепловая защита",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    if TARGET.exists():
        raise SystemExit("docs/index.html already exists. Nothing changed.")
    required = [CORPUS, CORPUS.parent / "manifest.json"] + [
        RESULTS / name for name in [
            "representative_topics.csv", "representative_record_profiles.csv",
            "representative_examples.csv",
        ]
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"Missing input: {path}")
    source_manifest = json.loads(required[1].read_text(encoding="utf-8"))
    if digest(CORPUS) != source_manifest["output_documents_sha256"]:
        raise SystemExit("Corpus checksum mismatch.")

    profiles = {}
    seeds = set()
    for row in read_csv(RESULTS / "representative_record_profiles.csv"):
        if int(row["k"]) != 10:
            continue
        record_id = str(row["ntrs_id"])
        topic = int(row["topic"])
        if not 0 <= topic < 10:
            raise SystemExit("Invalid topic ID.")
        entry = profiles.setdefault(record_id, {})
        if topic in entry:
            raise SystemExit("Duplicate profile cell.")
        value = float(row["relative_weight"])
        if not 0 <= value <= 1:
            raise SystemExit("Invalid topic weight.")
        entry[topic] = value
        seeds.add(int(row["representative_seed"]))
    if len(seeds) != 1:
        raise SystemExit("Expected one representative seed.")
    for record_id, profile in profiles.items():
        if set(profile) != set(range(10)) or abs(sum(profile.values()) - 1) > 1e-8:
            raise SystemExit(f"Invalid normalized profile: {record_id}")

    documents = []
    seen = set()
    with CORPUS.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            record_id = str(row["ntrs_id"])
            if record_id in seen:
                raise SystemExit("Duplicate corpus ID.")
            seen.add(record_id)
            weights = profiles.get(record_id)
            weights = [weights[i] for i in range(10)] if weights else None
            documents.append({
                "id": record_id, "title": row.get("title") or "",
                "abstract": row.get("abstract") or "",
                "hasFulltext": bool(row.get("text", "").strip()),
                "weights": weights,
                "leading": max(range(10), key=lambda i: weights[i]) if weights else None,
            })
    if not set(profiles).issubset(seen):
        raise SystemExit("Profiles refer to missing documents.")
    documents.sort(key=lambda row: row["id"])
    topics = []
    for row in read_csv(RESULTS / "representative_topics.csv"):
        if int(row["k"]) != 10:
            continue
        topic = int(row["topic"])
        if int(row["representative_seed"]) not in seeds:
            raise SystemExit("Representative seed mismatch.")
        values = [doc["weights"][topic] for doc in documents if doc["weights"] is not None]
        count = sum(doc["leading"] == topic for doc in documents)
        mean = sum(values) / len(values)
        if count != int(row["leading_record_count"]) or abs(mean - float(row["mean_relative_weight"])) > 1e-8:
            raise SystemExit("Topic summary mismatch.")
        topics.append({
            "id": topic, "label": LABELS[topic], "count": count, "mean": mean,
            "stability": float(row["mean_matched_cosine"]),
            "terms": row["top_terms"].split(" | "),
        })
    topics.sort(key=lambda row: row["id"])
    if [row["id"] for row in topics] != list(range(10)):
        raise SystemExit("Expected ten topics.")

    data = {
        "documents": documents, "topics": topics, "seed": next(iter(seeds)),
        "sources": [{"path": str(path.relative_to(ROOT)), "sha256": digest(path)} for path in required],
    }
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = TEMPLATE.replace("__PAYLOAD__", payload)
    DOCS.mkdir(exist_ok=True)
    TARGET.write_text(html, encoding="utf-8")
    (DOCS / ".nojekyll").touch(exist_ok=True)
    (DOCS / "atlas-build-manifest.json").write_text(json.dumps({
        "representation": "title + abstract, k=10; all corpus records in catalog",
        "documents": len(documents), "modeled": len(profiles), "seed": data["seed"],
        "sources": data["sources"], "generator_sha256": digest(Path(__file__)),
        "html_sha256": digest(TARGET),
        "limitations": ["No independent classification validation.", "Initialization stability is not classification confidence.", "No full text, local path or credentials included in published document records."],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PAGES ATLAS BUILT")
    print(json.dumps({"catalog_records": len(documents), "modeled_records": len(profiles), "html_bytes": TARGET.stat().st_size}, indent=2))
    print("Preview: python -m http.server 8000 --directory docs")


TEMPLATE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Атлас корпуса · Lavochkin Pipeline</title>
<style>
:root{--bg:#f4f5f2;--ink:#172d36;--muted:#54666d;--line:#d9e1df;--accent:#007e80}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}main{max-width:1240px;margin:auto;padding:36px 24px 70px}a{color:var(--accent)}header{padding:25px 0 34px;border-bottom:1px solid var(--line)}.eyebrow{text-transform:uppercase;letter-spacing:.17em;font-size:12px;color:var(--accent);font-weight:700}h1{font-size:clamp(32px,5vw,58px);letter-spacing:-.045em;line-height:1.12;margin:16px 0}h2{font-size:25px;letter-spacing:-.02em;margin-top:0}h3{font-size:18px}p{max-width:85ch}.muted,small{color:var(--muted)}nav{display:flex;gap:22px;flex-wrap:wrap}nav a{text-decoration:none}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:25px 0}.card,.panel{background:white;border:1px solid var(--line);border-radius:15px;padding:23px}.number{font-size:36px;letter-spacing:-.04em;font-weight:650}.grid{display:grid;grid-template-columns:1.35fr 1fr;gap:20px;margin:20px 0}.panel{margin-top:20px}.grid .panel{margin-top:0}button,input,select{font:inherit}button,select,input{border:1px solid #b8c9c6;border-radius:8px;background:white;padding:9px 12px;color:var(--ink)}button{cursor:pointer}button:hover{background:#eef6f4}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #e5a948;outline-offset:3px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.barrow{display:grid;grid-template-columns:minmax(120px,43%) 1fr 52px;align-items:center;gap:10px;width:100%;border:0;border-radius:8px;padding:9px 7px;text-align:left;font-size:14px}.barrow.active{background:#e4f3ef}.track{height:13px;background:#edf1f0;border-radius:4px;overflow:hidden}.fill{height:100%;border-radius:4px}.barval{text-align:right;font-variant-numeric:tabular-nums}.terms{display:flex;flex-wrap:wrap;gap:7px}.term{background:#edf4f1;border-radius:5px;padding:3px 8px;font-size:13px}.notice{border-left:3px solid #d5a448;padding:12px 17px;background:#fffaf0;border-radius:0 7px 7px 0}.chart{width:100%;height:auto;display:block}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:13px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-weight:500}td button{border:0;background:transparent;padding:0;text-align:left;color:var(--accent)}.tag{font-size:12px;color:var(--muted)}dialog{border:1px solid var(--line);border-radius:16px;max-width:850px;width:94%;max-height:90vh;padding:28px;color:var(--ink)}dialog::backdrop{background:#142b36aa}.abstract{white-space:pre-wrap;font-size:15px}.close{float:right}.footer{font-size:13px;color:var(--muted);margin-top:35px}.hidden{display:none}@media(max-width:800px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:1fr 1fr}main{padding:20px 14px}.panel{padding:17px}.barrow{font-size:12px}}
</style></head><body><main>
<header><div class="eyebrow">Lavochkin Pipeline / Research Atlas / v1.0</div>
<h1>Атлас корпуса<br>NASA NTRS</h1>
<p class="muted">Интерактивная исследовательская карта: содержание коллекции, устойчивость тематических компонентов и каталог записей.</p>
<nav><a href="#analytics">Аналитика</a><a href="#catalog">Каталог</a><a href="research/ntrs-topic-analysis/README.md">Научный отчёт · Markdown</a><a href="#method">Метод и ограничения</a></nav></header>
<div class="cards" id="cards"></div>
<div class="notice">Компоненты NMF — не подтверждённые классы документов. Вес — не вероятность правильной классификации. Показана базовая модель по названиям и аннотациям; 11 записей без аннотаций не имеют профиля.</div>
<section id="analytics"><div class="grid"><div class="panel"><h2>Карта содержания</h2><div class="toolbar"><label for="metric">Показатель</label><select id="metric"><option value="count">Записи с ведущим компонентом</option><option value="mean">Средний относительный вес</option></select></div><p class="muted"><small>Нажмите на строку: откроется описание и отфильтруется каталог. Повторное нажатие снимает фильтр.</small></p><div id="topicbars"></div></div>
<div class="panel"><h2 id="topicheading">Выберите компонент</h2><div id="topicdetail"><p class="muted">Узнайте, какие слова формируют компонент, насколько он воспроизводится и какие записи имеют наибольший относительный вес.</p></div></div></div>
<div class="grid"><div class="panel"><h2>Устойчивость компонентов</h2><p class="muted"><small>Средняя косинусная близость к сопоставленным компонентам девяти других инициализаций. Не оценка точности.</small></p><div id="stability"></div></div>
<div class="panel"><h2>Смешанность профилей</h2><div class="toolbar"><label for="distribution">Распределение</label><select id="distribution"><option value="max">Максимальный вес</option><option value="gap">Разница двух наибольших весов</option></select></div><div id="histogram"></div><p id="mixedsummary" class="muted"></p></div></div></section>
<section id="catalog" class="panel"><h2>Каталог материалов</h2><div class="toolbar"><label for="search">Поиск</label><input id="search" placeholder="NTRS ID, название, аннотация" style="flex:1;min-width:220px"><label for="filter">Компонент</label><select id="filter"><option value="all">Все записи</option><option value="none">Без модельного профиля</option></select><button id="reset">Сбросить</button><button id="download">Скачать выборку CSV</button></div><p id="resultcount" class="muted" aria-live="polite"></p><div class="tablewrap"><table><thead><tr><th>NTRS ID</th><th>Название</th><th>Ведущий компонент</th><th>Макс. вес</th></tr></thead><tbody id="records"></tbody></table></div><div class="toolbar" style="margin-top:16px"><button id="prev">Назад</button><span id="pageinfo"></span><button id="next">Далее</button></div></section>
<section id="method" class="panel"><h2>Метод и границы интерпретации</h2><p>Единица анализа — запись каталога. Название и аннотация объединены по одному разу. TF–IDF + NMF, k = 10. Все записи имеют равный вес при вычислении средних. Ведущий компонент — компонент с максимальным весом, а не единственная установленная тема.</p><p>Русские подписи — интерпретации терминов и характерных записей. Состав корпуса и инициализация меняют некоторые компоненты. Особенно нестабильно отдельное выделение плазмы и магнитных полей. Каталоги данных выделены по типу материала; остальные компоненты преимущественно предметные.</p><p>Портал — статический снимок опубликованных результатов, не подключение к PostgreSQL. Поиск выполняется в браузере. PDF и полные тексты не включены. Год публикации не выводится из NTRS ID. Полнота сбора, музейная релевантность и точность классификации не установлены.</p><details><summary>Файлы и происхождение</summary><p><a href="research/ntrs-topic-analysis/artifacts/representative_topics.csv">Терминные профили</a> · <a href="research/ntrs-topic-analysis/artifacts/representative_record_profiles.csv">Документные профили</a> · <a href="atlas-build-manifest.json">Манифест сборки</a></p><p id="seedinfo"></p></details></section>
<div class="footer">Независимый исследовательский проект. Не официальная система NASA, НПО Лавочкина или музея. Значения округлены только при отображении.</div>
</main><dialog id="detail"><button class="close" id="close">Закрыть</button><div id="detailbody"></div></dialog>
<script type="application/json" id="data">__PAYLOAD__</script>
<script>
'use strict';
const D=JSON.parse(document.getElementById('data').textContent),T=D.topics,R=D.documents;
const palette=['#306a84','#a86b44','#577c60','#92704f','#6276a5','#508d83','#8b607d','#7b8187','#007e80','#b68a3a'];
const $=id=>document.getElementById(id),fmt=x=>Number(x).toLocaleString('ru-RU',{maximumFractionDigits:3}),esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let selected=null,page=0,filtered=R;const size=15;
const modeled=R.filter(r=>r.weights!==null);
$('cards').innerHTML=[[R.length,'записи в каталоге'],[modeled.length,'с тематическим профилем'],[R.filter(r=>r.hasFulltext).length,'с непустым извлечённым текстом'],[10,'компонентов базовой модели']].map(([n,l])=>`<div class="card"><div class="number">${n}</div><div class="muted">${l}</div></div>`).join('');
T.forEach(t=>{const o=document.createElement('option');o.value=t.id;o.textContent=`${t.id}. ${t.label}`;$('filter').append(o)});
$('seedinfo').textContent=`Представительная модель: k=10, seed=${D.seed}. Контрольные суммы входов сохранены в манифесте сборки.`;
function selectTopic(id){selected=selected===id?null:id;$('filter').value=selected===null?'all':String(selected);page=0;renderBars();renderDetail();renderTable()}
function renderBars(){const metric=$('metric').value,sorted=[...T].sort((a,b)=>b[metric]-a[metric]),max=Math.max(...sorted.map(t=>t[metric]));$('topicbars').innerHTML=sorted.map(t=>`<button class="barrow ${selected===t.id?'active':''}" data-topic="${t.id}" aria-pressed="${selected===t.id}"><span>${esc(t.label)}</span><span class="track"><span class="fill" style="display:block;width:${t[metric]/max*100}%;background:${palette[t.id]}"></span></span><span class="barval">${metric==='count'?t.count:fmt(t.mean)}</span></button>`).join('');$('topicbars').querySelectorAll('button').forEach(b=>b.onclick=()=>selectTopic(Number(b.dataset.topic)))}
function renderDetail(){if(selected===null){$('topicheading').textContent='Выберите компонент';$('topicdetail').innerHTML='<p class="muted">Нажмите на строку диаграммы. Каталог ниже покажет записи с выбранным ведущим компонентом.</p>';return}const t=T[selected];$('topicheading').textContent=t.label;const examples=[...modeled].sort((a,b)=>b.weights[t.id]-a.weights[t.id]).slice(0,5);$('topicdetail').innerHTML=`<p>Средний вес: ${fmt(t.mean)} · Ведущий у ${t.count} записей<br>Устойчивость: ${fmt(t.stability)}</p><div class="terms">${t.terms.map(w=>`<span class="term">${esc(w)}</span>`).join('')}</div><h3>Характерные записи</h3><small class="muted">По максимальным относительным весам; не случайная выборка.</small><ol>${examples.map(r=>`<li><a href="#catalog" data-id="${esc(r.id)}">${esc(r.title)}</a> <small>(${fmt(r.weights[t.id])})</small></li>`).join('')}</ol>`;$('topicdetail').querySelectorAll('[data-id]').forEach(b=>b.onclick=ev=>{ev.preventDefault();showRecord(b.dataset.id)})}
function renderStability(){const h=360,w=620,left=42,top=22,bottom=42,pw=w-left-15,ph=h-top-bottom;let svg=`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Устойчивость десяти компонентов">`;[0,.25,.5,.75,1].forEach(v=>{const y=top+ph*(1-v);svg+=`<line x1="${left}" x2="${w-15}" y1="${y}" y2="${y}" stroke="#dfe6e3"/><text x="${left-8}" y="${y+4}" text-anchor="end" font-size="12" fill="#54666d">${fmt(v)}</text>`});T.forEach((t,i)=>{const x=left+i*pw/10+8,bw=pw/10-16,y=top+ph*(1-t.stability);svg+=`<rect x="${x}" y="${y}" width="${bw}" height="${ph*t.stability}" rx="3" fill="${palette[i]}"><title>${esc(t.label)}: ${fmt(t.stability)}</title></rect><text x="${x+bw/2}" y="${top+ph+21}" text-anchor="middle" font-size="12">${i}</text>`});$('stability').innerHTML=svg+'</svg><small class="muted">Номера соответствуют ID компонентов в фильтре каталога. Наведите курсор на столбец для названия и значения.</small>'}
function renderHistogram(){const mode=$('distribution').value,values=modeled.map(r=>{const a=[...r.weights].sort((a,b)=>b-a);return mode==='max'?a[0]:a[0]-a[1]}),bins=Array(10).fill(0);values.forEach(v=>bins[Math.min(9,Math.floor(v*10))]++);const w=620,h=330,left=42,top=30,ph=245,pw=560,max=Math.max(...bins,1);let svg=`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Гистограмма тематических весов">`;bins.forEach((n,i)=>{const x=left+i*pw/10+3,bw=pw/10-6,y=top+ph*(1-n/max);svg+=`<rect x="${x}" y="${y}" width="${bw}" height="${ph*n/max}" rx="3" fill="#007e80"><title>${(i/10).toFixed(1)}–${((i+1)/10).toFixed(1)}: ${n} записей</title></rect><text x="${x+bw/2}" y="${y-7}" text-anchor="middle" font-size="12">${n}</text><text x="${x+bw/2}" y="${top+ph+21}" text-anchor="middle" font-size="11">${fmt(i/10)}</text>`});$('histogram').innerHTML=svg+'</svg>';$('mixedsummary').textContent=mode==='max'?`У ${values.filter(v=>v>=.5).length} записей максимальный вес ≥ 0,5. Это не порог точности.`:`У ${values.filter(v=>v<.1).length} записей разрыв двух ведущих весов < 0,1. Интервалы гистограммы: [a; b), последний включает 1.`}
function renderTable(){const query=$('search').value.trim().toLocaleLowerCase('ru'),f=$('filter').value;filtered=R.filter(r=>(f==='all'||(f==='none'?r.weights===null:r.leading===Number(f)))&&(!query||(r.id+' '+r.title+' '+r.abstract).toLocaleLowerCase('ru').includes(query)));const pages=Math.max(1,Math.ceil(filtered.length/size));page=Math.min(page,pages-1);$('resultcount').textContent=`Найдено ${filtered.length} из ${R.length} записей. Фильтр темы использует только ведущий компонент.`;$('records').innerHTML=filtered.slice(page*size,(page+1)*size).map(r=>`<tr><td>${esc(r.id)}</td><td><button data-id="${esc(r.id)}">${esc(r.title)}</button></td><td>${r.weights?esc(T[r.leading].label):'Без профиля'}</td><td>${r.weights?fmt(Math.max(...r.weights)):'—'}</td></tr>`).join('');$('records').querySelectorAll('button').forEach(b=>b.onclick=()=>showRecord(b.dataset.id));$('pageinfo').textContent=`${page+1} / ${pages}`;$('prev').disabled=page===0;$('next').disabled=page>=pages-1}
function showRecord(id){const r=R.find(r=>r.id===id);$('detailbody').innerHTML=`<div class="eyebrow">NTRS ${esc(r.id)}</div><h2>${esc(r.title)}</h2><h3>Аннотация</h3><p class="abstract">${esc(r.abstract||'Аннотация отсутствует. Запись не включена в модель.')}</p><h3>Тематический профиль</h3>${r.weights?T.map(t=>`<div class="barrow"><span>${esc(t.label)}</span><span class="track"><span class="fill" style="display:block;width:${r.weights[t.id]*100}%;background:${palette[t.id]}"></span></span><span>${fmt(r.weights[t.id])}</span></div>`).join(''):'<p>Профиль отсутствует.</p>'}<p class="muted"><small>Наличие извлечённого текста: ${r.hasFulltext?'да':'нет'}. Непустота не подтверждает качество. Модель использует только название и аннотацию.</small></p>`;$('detail').showModal()}
$('close').onclick=()=>$('detail').close();$('metric').onchange=renderBars;$('distribution').onchange=renderHistogram;$('search').oninput=()=>{page=0;renderTable()};$('filter').onchange=()=>{const f=$('filter').value;selected=(f==='all'||f==='none')?null:Number(f);page=0;renderBars();renderDetail();renderTable()};$('reset').onclick=()=>{$('search').value='';$('filter').value='all';selected=null;page=0;renderBars();renderDetail();renderTable()};$('prev').onclick=()=>{page--;renderTable()};$('next').onclick=()=>{page++;renderTable()};
$('download').onclick=()=>{const safe=v=>{let s=String(v??'');if(/^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'},rows=[['ntrs_id','title','leading_topic','max_weight'],...filtered.map(r=>[r.id,r.title,r.weights?T[r.leading].label:'',r.weights?Math.max(...r.weights):''])],blob=new Blob(['\ufeff'+rows.map(row=>row.map(safe).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='ntrs_catalog_selection.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
renderBars();renderDetail();renderStability();renderHistogram();renderTable();
</script></body></html>"""

if __name__ == "__main__":
    main()
