(() => {
  const socket = io();
  const links = [...document.querySelectorAll('.conversation-link')];
  const empty = document.getElementById('empty-state');
  const area = document.getElementById('message-area');
  const form = document.getElementById('message-form');
  const messagesEl = document.getElementById('messages');
  const input = document.getElementById('message-input');
  const titleEl = document.getElementById('active-title');
  const intro = document.getElementById('intro-text');
  const typing = document.getElementById('typing-indicator');
  let activeId = null, activeKind = null, typingTimer = null;
  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function renderMessage(m) {
    const el = document.createElement('div');
    el.className = 'message-row ' + (m.mine ? 'mine' : '');
    el.innerHTML = `<div class="message-avatar">${esc((m.name||m.username||'?').slice(0,1).toUpperCase())}</div><div class="message-content"><div class="message-meta"><b>${esc(m.name)}</b><span>@${esc(m.username)}</span><time>${esc(m.time)}</time></div><div class="bubble">${esc(m.body)}</div><div class="message-tools"><button type="button" title="React (coming soon)">♡</button><button type="button" title="Reply (coming soon)">↩</button></div></div>`;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  async function selectConversation(link) {
    activeId = Number(link.dataset.id); activeKind = link.dataset.kind;
    links.forEach(l => l.classList.toggle('selected', l === link));
    titleEl.textContent = link.dataset.title;
    intro.textContent = activeKind === 'channel' ? 'Broadcast channel' : activeKind === 'group' ? 'Group conversation' : 'Private conversation';
    empty.classList.add('hidden'); area.classList.remove('hidden'); form.classList.remove('hidden');
    messagesEl.innerHTML = ''; typing.textContent = '';
    socket.emit('join_conversation', {conversation_id: activeId});
    try {
      const res = await fetch(`/api/conversations/${activeId}/messages`);
      const data = await res.json();
      if (!res.ok) throw new Error('Could not load messages');
      data.forEach(renderMessage);
    } catch (e) { typing.textContent = 'Could not load this conversation. Refresh and try again.'; }
  }
  links.forEach(link => link.addEventListener('click', () => selectConversation(link)));
  const initial = new URLSearchParams(location.search).get('conversation');
  const first = initial ? links.find(l => l.dataset.id === initial) : links[0];
  if (first) selectConversation(first);

  form.addEventListener('submit', e => {
    e.preventDefault();
    const body = input.value.trim();
    if (!body || !activeId) return;
    socket.emit('send_message', {conversation_id: activeId, body});
    input.value = ''; input.focus();
  });
  socket.on('new_message', m => { if (Number(m.conversation_id || activeId) === activeId) renderMessage({...m, mine: false}); });
  socket.on('message_sent', m => { if (activeId) renderMessage({...m, mine: true}); });
  // Include the conversation id with broadcast messages for clients on the same room.
  socket.on('typing', d => { typing.textContent = `${d.name} is typing…`; clearTimeout(typingTimer); typingTimer = setTimeout(() => typing.textContent = '', 1800); });
  input.addEventListener('input', () => { if (activeId) socket.emit('typing', {conversation_id: activeId}); });

  document.getElementById('new-dm-toggle').addEventListener('click', () => document.getElementById('people-panel').classList.toggle('hidden'));
  document.getElementById('find-people').addEventListener('click', () => document.getElementById('people-panel').classList.toggle('hidden'));
  document.getElementById('new-space-toggle').addEventListener('click', () => document.getElementById('create-space').classList.toggle('hidden'));
  document.getElementById('create-group').addEventListener('click', () => { document.getElementById('create-space').classList.remove('hidden'); document.querySelector('#create-space input').focus(); });
})();
