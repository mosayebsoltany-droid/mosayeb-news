const html = `<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="سامانه خبرگزاری هوشمند"><title>خبرگزاری مسیب | اخبار روز</title>
<style>body{margin:0;background:#f6f8fb;color:#172b40;font:16px system-ui,Tahoma,sans-serif}header{background:#102b46;color:white;padding:26px max(20px,calc((100% - 980px)/2))}header h1{margin:0 0 8px}header p{margin:0;color:#d5e3f0}main{max-width:980px;margin:35px auto;padding:0 20px}.lead{margin-bottom:24px}.news{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.card{background:white;border:1px solid #e4e8ef;border-radius:14px;padding:20px}.card h2{font-size:19px;margin:0 0 12px}.card p{line-height:1.9}.card a{color:#155c9b}footer{text-align:center;color:#657589;padding:35px}</style></head>
<body><header><h1>خبرگزاری مسیب</h1><p>سامانه هوشمند مدیریت و انتشار اخبار</p></header><main><div class="lead"><h2>آخرین اخبار</h2><p id="status" role="status">در حال دریافت اخبار...</p></div><section class="news" id="news"></section></main><footer>نسخه آزمایشی سامانه خبری</footer>
<script>
(async()=>{const status=document.getElementById('status'),list=document.getElementById('news');try{const response=await fetch('/api/news');const data=await response.json();if(!response.ok)throw Error('unavailable');const articles=data.articles||[];status.textContent=articles.length?'آخرین مطالب منتشرشده':'هنوز خبری منتشر نشده است.';for(const article of articles){const card=document.createElement('article');card.className='card';const title=document.createElement('h2');title.textContent=article.title;card.append(title);if(article.summary){const p=document.createElement('p');p.textContent=article.summary;card.append(p)}if(article.published_at){const time=document.createElement('small');time.textContent=new Date(article.published_at).toLocaleDateString('fa-IR');card.append(time)}list.append(card)}}catch{status.textContent='دریافت اخبار موقتاً امکان‌پذیر نیست.'}})();
</script></body></html>`;
const headers = {'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'};
export default {
 async fetch(request,env) {
  const url=new URL(request.url);
  if(url.pathname==='/health') return Response.json({status:'ok'});
  if(url.pathname==='/api/news'){
   if(!env.SUPABASE_URL||!env.SUPABASE_PUBLISHABLE_KEY) return new Response(JSON.stringify({articles:[],configured:false}),{headers});
   try{
    const base=new URL(env.SUPABASE_URL);
    if(base.protocol!=='https:' || !base.hostname.endsWith('.supabase.co')) throw Error('Invalid Supabase host');
    const endpoint=new URL('/rest/v1/news_articles',base);
    endpoint.searchParams.set('select','id,title,summary,slug,published_at');
    endpoint.searchParams.set('status','eq.published');
    endpoint.searchParams.set('order','published_at.desc');
    endpoint.searchParams.set('limit','30');
    const result=await fetch(endpoint.toString(),{headers:{apikey:env.SUPABASE_PUBLISHABLE_KEY,'accept':'application/json'},signal:AbortSignal.timeout(8000)});
    if(!result.ok) throw Error('Supabase request failed');
    return new Response(JSON.stringify({articles:await result.json(),configured:true}),{headers});
   }catch{return new Response(JSON.stringify({error:'News service unavailable'}),{status:503,headers})}
  }
  if(url.pathname!=='/')return new Response('Not Found',{status:404});
  return new Response(html,{headers:{'content-type':'text/html; charset=utf-8','x-content-type-options':'nosniff','referrer-policy':'strict-origin-when-cross-origin','content-security-policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"}});
 }
};
