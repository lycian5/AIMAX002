const CACHE = 'forklift-log-v2';
const PRECACHE = [
  '/',
  '/manifest.json',
  '/static/icon.svg',
  'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const req = e.request;

  // HTML 문서는 네트워크 우선: 온라인이면 항상 최신 버전을 받아오고,
  // 오프라인일 때만 마지막으로 받아둔 캐시를 사용한다.
  if (req.mode === 'navigate' || req.destination === 'document') {
    e.respondWith(
      fetch(req)
        .then(res => {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(req, clone));
          return res;
        })
        .catch(() => caches.match(req).then(cached => cached || caches.match('/')))
    );
    return;
  }

  // 그 외 정적 자원(아이콘, 매니페스트, 라이브러리)은 캐시 우선
  e.respondWith(
    caches.match(req).then(cached =>
      cached || fetch(req).then(res => {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(req, clone));
        return res;
      })
    )
  );
});
