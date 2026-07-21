async function refreshLiveFeed() {
  const list = document.getElementById("live-feed");
  if (!list) return;
  try {
    const res = await fetch("/api/live-feed");
    const entries = await res.json();
    if (entries.length === 0) {
      list.innerHTML = '<li class="empty">Noch keine Ereignisse.</li>';
      return;
    }
    list.innerHTML = entries
      .map(
        (e) => `<li><span class="feed-time">${e.timestamp.slice(11, 16)}</span><span class="feed-text">${e.text}</span></li>`
      )
      .join("");
  } catch (err) {
    console.error("Live-Feed konnte nicht geladen werden", err);
  }
}

setInterval(refreshLiveFeed, 5000);
