function openRespondModal(vacancyId, contacts, resumeLink) {
  const modal = document.getElementById('respond-modal');
  document.getElementById('modal-vacancy-id').textContent = vacancyId;
  document.getElementById('modal-contacts').textContent = contacts || 'Контакты не указаны';
  document.getElementById('resume-link').value = resumeLink;
  modal.classList.add('open');
}

function closeRespondModal() {
  const modal = document.getElementById('respond-modal');
  modal.classList.remove('open');
}

async function copyResumeLink() {
  const input = document.getElementById('resume-link');
  try {
    await navigator.clipboard.writeText(input.value);
    alert('Ссылка скопирована!');
  } catch (e) {
    input.select();
    document.execCommand('copy');
    alert('Ссылка скопирована!');
  }
}
