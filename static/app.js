/* PocketSmart shared helpers + result renderers */
const PS = {
  esc(s){return String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))},
  inr(n){return "₹"+Number(n||0).toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2})},
  pretty(s){s=String(s||"").replace(/_/g," ");return s.charAt(0).toUpperCase()+s.slice(1)},
  icons:{amazon:"fa-brands fa-amazon",flipkart:"fa-solid fa-cart-shopping",ikea:"fa-solid fa-store",myntra:"fa-solid fa-cart-shopping",ajio:"fa-solid fa-cart-shopping",
    bluestone:"fa-solid fa-gem",google:"fa-solid fa-magnifying-glass"},
  label(k){return {oyorooms:"Oyorooms",makemytrip:"Makemytrip",bookmyshow:"Bookmyshow",bigbasket:"Bigbasket",nobroker:"Nobroker"}[k]||PS.pretty(k)},
  links(obj, cls="chip", prefix=""){
    if(!obj) return "";
    return `<div class="links">${prefix}${Object.entries(obj).map(([k,u])=>`<a class="${cls}" href="${PS.esc(u)}" target="_blank" rel="noopener noreferrer"><i class="${PS.icons[k]||"fa-solid fa-cart-shopping"}"></i> ${PS.label(k)}</a>`).join("")}</div>`;
  },
  suggestions(list,title="Additional Suggestions",icon="fa-lightbulb"){
    if(!list||!list.length) return "";
    return `<div class="panel"><div class="panel-hd alt"><span><i class="fa-solid ${icon}"></i> ${title}</span></div><div class="panel-body"><ul class="sugg">${list.map(s=>`<li><i class="fa-solid fa-circle-check"></i><span>${PS.esc(s)}</span></li>`).join("")}</ul></div></div>`;
  },
  catIcon:{lighting:"fa-lightbulb",ceiling_fans:"fa-fan",furniture:"fa-couch",dining_tables:"fa-utensils",venue:"fa-location-dot",catering:"fa-utensils",decoration:"fa-palette",entertainment:"fa-music",contingency:"fa-tag"},

  renderHome(r){
    const cats=(r.budget_breakdown||[]).map(c=>`
      <div class="cat"><h4><i class="fa-solid ${PS.catIcon[c.category]||"fa-list"}"></i> ${PS.esc(PS.pretty(c.category))}</h4>
      <div class="alloc">Allocation: ${PS.inr(c.allocation)}</div>
      <div style="overflow-x:auto"><table class="t"><thead><tr><th>Item</th><th>Description</th><th>Price</th><th>Quantity</th><th>Shopping Links</th></tr></thead><tbody>
      ${(c.items||[]).map(i=>`<tr><td><b>${PS.esc(i.name)}</b></td><td>${PS.esc(i.description)}</td><td>${PS.inr(i.estimated_price)}</td><td>${PS.esc(i.quantity)}</td><td>${PS.links(i.shopping_links)}</td></tr>`).join("")}
      </tbody></table></div></div>`).join("");
    return `<div class="result-title">Your Personalized Budget Plan</div>
      <div class="panel"><div class="panel-hd"><span><i class="fa-solid fa-chart-pie"></i> Budget Summary</span></div>
      <div class="panel-body"><div class="sum-row"><span>Total Budget: ${PS.inr(r.total_budget)}</span><span>Remaining Budget: <span class="g">${PS.inr(r.remaining_budget)}</span></span></div></div></div>
      ${cats}${PS.suggestions(r.additional_suggestions)}`;
  },

  renderParty(r){
    const cats=(r.budget_breakdown||[]).map(c=>`
      <div class="panel"><div class="panel-hd alt" style="background:#fff;color:var(--navy);border-bottom:1px solid var(--line)"><span><i class="fa-solid ${PS.catIcon[(c.category||"").toLowerCase()]||"fa-list"}" style="color:var(--orange)"></i> ${PS.esc(PS.pretty(c.category))}</span><span>${PS.inr(c.allocation)}</span></div>
      <div class="panel-body">${(c.items||[]).map(i=>`<div class="pitem"><div class="top"><div><div class="nm">${PS.esc(i.name)}</div><div class="ds">${PS.esc(i.description)}</div></div><div class="price">${PS.inr(i.estimated_price)}</div></div>
      ${i.shopping_links?PS.links(i.shopping_links,"chip",'<span style="font-size:.72rem;font-weight:700;color:var(--navy);margin-right:4px">Shop on:</span>'):""}</div>`).join("")}</div></div>`).join("");
    const allocated=(r.total_budget||0)-(r.remaining_budget||0);
    const venues=(r.venue_suggestions||[]).length?`<div class="panel"><div class="panel-hd alt" style="background:#fff;color:var(--navy)"><span><i class="fa-solid fa-location-dot" style="color:var(--orange)"></i> Venue Suggestions</span></div><div class="panel-body">${r.venue_suggestions.map(v=>`<div class="pitem"><div class="top"><div><div class="nm">${PS.esc(v.name)}</div><div class="ds">Type: ${PS.esc(v.type||"-")} &nbsp; Capacity: ${PS.esc(v.capacity||"-")}</div>${PS.links(v.search_links)}</div><div class="price">${PS.inr(v.estimated_cost)}</div></div></div>`).join("")}</div></div>`:"";
    return `<div class="panel"><div class="panel-hd" style="background:#fff;color:var(--navy);border-bottom:1px solid var(--line)"><span style="font-size:1.1rem">Your Party Budget Plan</span><button class="btn btn-primary no-print" style="padding:7px 16px;font-size:.75rem" onclick="window.print()"><i class="fa-solid fa-print"></i> Print/Save</button></div>
      <div class="panel-body"><div style="color:var(--blue);font-weight:700;font-size:1.05rem">Budget: ${PS.inr(r.total_budget)}</div></div></div>
      ${cats}
      <div class="panel totals"><div><span>Total Budget</span><span>${PS.inr(r.total_budget)}</span></div><div><span>Allocated</span><span>${PS.inr(allocated)}</span></div><div><span>Remaining</span><span>${PS.inr(r.remaining_budget)}</span></div></div>
      ${venues}${PS.suggestions(r.additional_suggestions)}`;
  },

  renderJewelry(r){
    const o=r.outfit_analysis;
    const outfit=o?`<div class="panel"><div class="panel-hd" style="background:#f4f7fb;color:var(--navy)"><span><i class="fa-solid fa-shirt"></i> Outfit Analysis</span></div><div class="panel-body"><div class="outfit"><span><i class="fa-solid fa-palette"></i> <b>Colors:</b> ${PS.esc((o.colors||[]).join(", "))}</span><span><i class="fa-solid fa-heart"></i> <b>Style:</b> ${PS.esc(o.style)}</span><span><i class="fa-solid fa-user-tie"></i> <b>Formality:</b> ${PS.esc(o.formality)}</span></div></div></div>`:"";
    const items=(r.jewelry_recommendations||[]).map(i=>`<div class="pitem"><div class="top"><div class="nm"><i class="fa-solid fa-circle" style="color:var(--blue);font-size:.7rem"></i> ${PS.esc(i.item_type)}</div><span class="price badge">${PS.inr(i.estimated_price)}</span></div>
      <div class="ds"><b>Description:</b> ${PS.esc(i.description)}</div><div class="ds"><b>Style:</b> ${PS.esc(i.style)}</div>
      <div class="ds" style="margin-top:8px"><b><i class="fa-solid fa-cart-shopping"></i> Shop For This:</b></div>${PS.links(i.shopping_links)}</div>`).join("");
    return `<div class="result-title">Your Personalized Jewelry Recommendations</div>
      <div class="panel"><div class="panel-hd"><span><i class="fa-solid fa-chart-pie"></i> Budget Summary</span></div><div class="panel-body"><div class="sum-row"><span>Total Budget: ${PS.inr(r.total_budget)}</span><span>Remaining Budget: <span class="g">${PS.inr(r.remaining_budget)}</span></span></div></div></div>
      ${outfit}
      <div class="panel"><div class="panel-hd"><span><i class="fa-solid fa-gem"></i> Jewelry Recommendations</span></div><div class="panel-body">${items}</div></div>
      ${PS.suggestions(r.styling_tips,"Styling Tips")}`;
  },

  render(type,r){return type==="home"?PS.renderHome(r):type==="party"?PS.renderParty(r):PS.renderJewelry(r)},

  async submit({url,body,isForm,btn,spinner,out,type}){
    const label=btn.innerHTML; btn.disabled=true; spinner.classList.add("show"); out.innerHTML="";
    try{
      const res=await fetch(url,{method:"POST",credentials:"same-origin",
        headers:isForm?{}:{"Content-Type":"application/json"},body:isForm?body:JSON.stringify(body)});
      if(res.status===401){location.href="/login";return}
      const data=await res.json().catch(()=>({}));
      if(!res.ok){
        const d=data.detail; const msg=Array.isArray(d)?d.map(e=>(e.loc||[]).slice(-1)[0]+": "+e.msg).join("; "):(d||"Something went wrong");
        throw new Error(msg);
      }
      out.innerHTML=PS.render(type,data);
      out.scrollIntoView({behavior:"smooth",block:"start"});
    }catch(e){
      out.innerHTML=`<div class="alert alert-error show">${PS.esc(e.message)}</div>`;
    }finally{btn.disabled=false;btn.innerHTML=label;spinner.classList.remove("show")}
  },

  async logout(){await fetch("/logout",{method:"POST",credentials:"same-origin",redirect:"manual"});location.href="/login"}
};
