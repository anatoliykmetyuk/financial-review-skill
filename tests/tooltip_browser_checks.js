// Run against a rendered category chart inside the visualization wrapper:
// playwright-cli run-code --filename tests/tooltip_browser_checks.js
async (page) => {
  const frame=page.frameLocator('iframe');
  const tip=frame.locator('[data-details]');
  const point=()=>frame.locator('.point').first();
  const visible=()=>tip.waitFor({state:'visible',timeout:2000});
  let phase='initial';
  const hidden=async()=>{try{await tip.waitFor({state:'hidden',timeout:2000});}catch(e){throw new Error(phase+': '+e.message);}};
  const moveWithin=async()=>{
    const box=await point().boundingBox();
    await page.mouse.move(box.x+box.width/2+1,box.y+box.height/2+1);
  };
  const widths=[736,1024,390];
  for(const width of widths){
    await page.setViewportSize({width,height:900});
    await frame.locator('[data-title]').hover();
    await point().hover();await visible();
    for(let cycle=0;cycle<3;cycle++){
      // A focus loss while the pointer remains over the dot used to leave it hidden.
      await frame.locator('[data-plot]').evaluate(()=>window.dispatchEvent(new Event('blur')));
      phase='focus loss';await hidden();await moveWithin();await visible();
      phase='Escape';await point().focus();await page.keyboard.press('Escape');await hidden();
      await point().click();await visible();
      phase='leave point';await frame.locator('[data-title]').hover();await hidden();
      await point().hover();await visible();
    }
    const details=await tip.evaluate(e=>{
      const columns=['time','amount','description'].map(name=>
        [...e.querySelectorAll('.detail-'+name)].map(cell=>cell.getBoundingClientRect().left));
      const bounds=e.getBoundingClientRect();
      return {columns,aligned:columns.every(xs=>xs.every(x=>Math.abs(x-xs[0])<1)),
        fits:bounds.left>=0 && bounds.right<=document.documentElement.clientWidth+1};
    });
    if(!details.aligned || !details.fits)throw new Error(`Tooltip layout failed at ${width}px: ${JSON.stringify(details)}`);
    phase='leave point';await frame.locator('[data-title]').hover();await hidden();
  }
  const touch=await page.context().browser().newContext({hasTouch:true,viewport:{width:390,height:900}});
  try {
    const touchPage=await touch.newPage();await touchPage.goto(page.url());
    const touchFrame=touchPage.frameLocator('iframe');
    await touchFrame.locator('.point').first().tap();
    await touchFrame.locator('[data-details]').waitFor({state:'visible',timeout:2000});
    await touchFrame.locator('[data-title]').tap();
    await touchFrame.locator('[data-details]').waitFor({state:'hidden',timeout:2000});
  } finally {await touch.close();}
  return {passed:true,widths,focusRecoveryCycles:9,touch:'tap shows; outside tap dismisses'};
}
