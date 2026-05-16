const root=document.documentElement;
const btn=document.getElementById('themeToggle');
if(btn){btn.addEventListener('click',()=>{root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';localStorage.setItem('theme',root.dataset.theme);});
const saved=localStorage.getItem('theme');if(saved)root.dataset.theme=saved;}
