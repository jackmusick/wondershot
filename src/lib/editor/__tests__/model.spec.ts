import { describe, it, expect } from 'vitest';
import { serializeItem, deserializeItem, type Item } from '$lib/editor/model';

const cases: Record<string, any> = {
  arrow: { type:'arrow', p1:[1,2], p2:[3,4], color:'#ff0000ff', width:4, pos:[0,0], rotation:0, origin:[0,0] },
  line: { type:'line', p1:[1,2], p2:[3,4], color:'#00ff00ff', width:2, pos:[0,0], rotation:0, origin:[0,0] },
  rect: { type:'rect', rect:[0,0,10,20], color:'#112233ff', width:3, pos:[0,0], rotation:0, origin:[0,0] },
  rect_fill: { type:'rect', rect:[0,0,10,20], color:'#112233ff', width:3, fill:'#445566ff', pos:[0,0], rotation:0, origin:[0,0] },
  ellipse: { type:'ellipse', rect:[0,0,10,20], color:'#112233ff', width:3, pos:[0,0], rotation:0, origin:[0,0] },
  highlight: { type:'highlight', rect:[0,0,60,20], color:'#ffe000', pos:[0,0], rotation:0, origin:[0,0] },
  freehand: { type:'freehand', points:[[1,2],[3,4],[5,6]], color:'#000000ff', width:2, pos:[0,0], rotation:0, origin:[0,0] },
  text: { type:'text', text:'hi', color:'#ffffffff', family:'Sans', point_size:24, bold:true, text_width:-1, align:'left', pos:[0,0], rotation:0, origin:[0,0] },
  step: { type:'step', number:3, color:'#3b82f6ff', radius:16, pos:[5,5], rotation:0, origin:[0,0] },
  pixelate: { type:'pixelate', rect:[20,20,60,40], block:14, pos:[0,0], rotation:0, origin:[0,0] },
  blur: { type:'blur', rect:[20,20,60,40], radius:12, pos:[0,0], rotation:0, origin:[0,0] },
};

describe('editor model round-trip', () => {
  for (const [name, json] of Object.entries(cases)) {
    it(`${name} round-trips to exact Python JSON`, () => {
      const item = deserializeItem(json) as Item;
      expect(serializeItem(item)).toEqual(json);
    });
  }
  it('rect without fill omits the fill key', () => {
    const item = deserializeItem(cases.rect) as Item;
    expect('fill' in serializeItem(item)).toBe(false);
  });
});
