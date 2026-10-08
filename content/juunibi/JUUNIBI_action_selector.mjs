/** JUUNIBI pre-speech action selector. Zero dependencies. Browser or Node.js 20+.
 * Caller must supply persistent adapter if localStorage is absent.
 * Generation happens via caller-supplied server endpoint; never expose API credentials in browser.
 */
export class JuunibiActionSelector {
  constructor(dataset, {storage = globalThis.localStorage, storageKey = 'juunibi:pre_speech:v1', generate = null} = {}) {
    if (!Array.isArray(dataset?.actions) || dataset.actions.length === 0) throw new Error('Missing dataset.actions');
    this.dataset = dataset;
    this.storage = storage;
    this.storageKey = storageKey;
    this.generate = generate;
    const raw = storage?.getItem(storageKey);
    try { this.state = raw ? JSON.parse(raw) : {used:[], created:[]}; } catch { this.state = {used:[],created:[]}; }
    if (!Array.isArray(this.state.used) || !Array.isArray(this.state.created)) this.state = {used:[],created:[]};
    this.state.created = this.state.created.filter(a => a && typeof a.id === 'string' && typeof a.text === 'string');
    this.state.used = this.state.used.filter(id => typeof id === 'string');
  }
  all() { return [...this.dataset.actions, ...this.state.created]; }
  save() { if (!this.storage) throw new Error('Persistent storage required to guarantee non-repetition'); this.storage.setItem(this.storageKey, JSON.stringify(this.state)); }
  static normalized(s) { return String(s).toLowerCase().normalize('NFKC').replace(/[^а-яёa-z0-9]+/g,' ').trim(); }
  static shingles(s) { const a=JuunibiActionSelector.normalized(s).split(' ').filter(Boolean); return new Set(a.slice(0,-2).map((_,i)=>a.slice(i,i+3).join(' '))); }
  static similarity(a,b) { const x=this.shingles(a),y=this.shingles(b);let common=0; for(const z of x)if(y.has(z))common++;return common/Math.max(1,x.size+y.size-common); }
  validate(action) {
    if (!action || typeof action.text !== 'string') return false;
    const s=action.text.trim();
    if (s.length < 55 || s.length > 600 || /juunibi|джууниби|«|»|\bговорит\b/i.test(s)) return false;
    const n=JuunibiActionSelector.normalized(s);
    return !this.all().some(a => {
      const m=JuunibiActionSelector.normalized(a.text);
      return n===m || JuunibiActionSelector.similarity(s,a.text)>0.42;
    });
  }
  async next({category, context}={}) {
    if (!this.storage) throw new Error('Supply persistent storage adapter before selection');
    const used=new Set(this.state.used);
    let candidates=this.all().filter(a=>!used.has(a.id) && (!category||a.category===category));
    if (!candidates.length && typeof this.generate==='function') {
      for (let attempt=0; attempt<5 && !candidates.length; attempt++) {
        const proposal=await this.generate({category,context,existing:this.all().map(a=>a.text)});
        if (this.validate(proposal)) {
          const created={id:`JUA-GEN-${crypto.randomUUID()}`, category:proposal.category||category||'новое',emotion:proposal.emotion||'warm',duration_seconds:proposal.duration_seconds||4.5,text:proposal.text,tags:['generated']};
          this.state.created.push(created);
          this.save();
          candidates=[created];
        }
      }
    }
    if (!candidates.length) throw new Error('Unused actions exhausted; generation unavailable or invalid. No repetition performed.');
    // Uniformly select one of unused entries in the matching pool.
    const choice=candidates[Math.floor(Math.random()*candidates.length)];
    this.state.used.push(choice.id);
    this.save();
    return choice;
  }
  stats() {return {total:this.all().length, used:new Set(this.state.used).size,unused:this.all().filter(a=>!this.state.used.includes(a.id)).length};}
}

/** Example web integration:
 * import data from './JUUNIBI_365_cinematic_actions.json';
 * const selector = new JuunibiActionSelector(data, {
 *   generate: async ({category,context,existing}) => {
 *     const res = await fetch('/api/juunibi/generate-action', {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({category,context,existing})});
 *     if(!res.ok) throw new Error('AI generation failed');
 *     return res.json();
 *   }
 * });
 * const action=await selector.next();
 * await playAnimation(action); // implement using your UI/animation engine
 * await speakAIReply();
 * Note: for multi-tab or multi-device strict no-repeat, move state and selection to a transactional server-side DB.
 */
