import {defineConfig} from 'vite';
import {readFileSync} from 'node:fs';
export default defineConfig({
  plugins:[{name:'shared-appearance-prepaint',transformIndexHtml(html){
    const prepaint=readFileSync(new URL('./node_modules/@doshi-experiments/design-system/dist/prepaint.js',import.meta.url),'utf8');
    return html.replace('<!-- Shared appearance prepaint -->',`<script>${prepaint}</script>`);
  }}],
  base:'./', server:{proxy:{'/api':'http://127.0.0.1:8040'}},
  build:{rollupOptions:{onwarn(warning,warn){
    if(warning.code==='MODULE_LEVEL_DIRECTIVE' && warning.message.includes('use client')) return;
    warn(warning);
  }}},
});
