import { describe, it, expect } from 'vitest';
import { serializeItem, deserializeItem, type Item } from '$lib/editor/model';

// One of each item type -> sidecar items array -> back -> identical serialization.
const items: any[] = [
  {type:'arrow',p1:[1,2],p2:[3,4],color:'#ff0000ff',width:4,pos:[0,0],rotation:0,origin:[0,0]},
  {type:'rect',rect:[0,0,10,20],color:'#112233ff',width:3,pos:[0,0],rotation:0,origin:[0,0]},
  {type:'highlight',rect:[0,0,60,20],color:'#ffe000',pos:[0,0],rotation:0,origin:[0,0]},
  {type:'text',text:'hi',color:'#ffffffff',family:'sans-serif',point_size:24,bold:true,text_width:-1,align:'left',pos:[5,5],rotation:0,origin:[0,0]},
  {type:'step',number:1,color:'#3b82f6ff',radius:16,pos:[9,9],rotation:0,origin:[0,0]},
  {type:'pixelate',rect:[20,20,60,40],block:14,pos:[0,0],rotation:0,origin:[0,0]},
];
describe('sidecar items round-trip', () => {
  it('every item type serialize->deserialize->serialize is identical', () => {
    for (const json of items) {
      const item = deserializeItem(json) as Item;
      expect(serializeItem(item)).toEqual(json);
    }
  });
  it('a full items array round-trips through a sidecar doc shape', () => {
    const doc = { version:1, bases:1, items: items.map(j => serializeItem(deserializeItem(j) as Item)), effects:{rounded:false,corner_radius:12,fade:false,fade_height:64} };
    const reloaded = doc.items.map(j => serializeItem(deserializeItem(j) as Item));
    expect(reloaded).toEqual(items);
  });
});
