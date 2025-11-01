const form = document.getElementById('optimization-form');
const addRowButton = document.getElementById('add-row');
const slitRowsContainer = document.getElementById('slit-rows');
const resultSection = document.getElementById('result-section');
const resultSummary = document.getElementById('result-summary');
const resultTableBody = document.querySelector('#result-table tbody');
const errorSection = document.getElementById('error-section');
const errorMessage = document.getElementById('error-message');
const rowTemplate = document.getElementById('slit-row-template');

function addSlitRow(width = '', instruction = '') {
  const fragment = rowTemplate.content.cloneNode(true);
  const row = fragment.querySelector('.slit-row');
  const widthInput = fragment.querySelector('.slit-width');
  const instructionInput = fragment.querySelector('.slit-instruction');
  widthInput.value = width;
  instructionInput.value = instruction;
  const removeButton = fragment.querySelector('.remove');
  removeButton.addEventListener('click', () => {
    row.remove();
    toggleRemoveButtons();
  });
  slitRowsContainer.appendChild(fragment);
  toggleRemoveButtons();
}

function toggleRemoveButtons() {
  const rows = slitRowsContainer.querySelectorAll('.slit-row');
  rows.forEach((row) => {
    const button = row.querySelector('.remove');
    button.disabled = rows.length <= 1;
  });
}

function collectFormData() {
  const baseWidth = parseFloat(form.baseWidth.value);
  const maxLength = parseFloat(form.maxLength.value);
  const widths = [];
  const instructions = [];

  slitRowsContainer.querySelectorAll('.slit-row').forEach((row) => {
    const widthValue = parseFloat(row.querySelector('.slit-width').value);
    const instructionValue = parseFloat(row.querySelector('.slit-instruction').value);
    if (!Number.isNaN(widthValue) && !Number.isNaN(instructionValue)) {
      widths.push(widthValue);
      instructions.push(instructionValue);
    }
  });

  return { baseWidth, maxLength, widths, instructions };
}

async function submitForm(event) {
  event.preventDefault();
  hideResult();
  hideError();

  const payload = collectFormData();
  if (payload.widths.length === 0) {
    showError('スリット幅と指示数を入力してください。');
    return;
  }

  try {
    const response = await fetch('/optimize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!data.success) {
      showError(data.message || '最適化に失敗しました。');
      return;
    }
    renderResult(data.result, payload);
  } catch (error) {
    showError('サーバーとの通信に失敗しました。');
  }
}

function renderResult(result, payload) {
  const { rolls, zLength, widthUsage, slack, totalRolls, produced, differences } = result;
  resultSummary.innerHTML = `
    <p>共通巻き長さ Z = <strong>${zLength.toFixed(2)}</strong> m</p>
    <p>総ロール数 = <strong>${totalRolls}</strong></p>
    <p>原反使用幅 = <strong>${widthUsage.toFixed(2)}</strong> mm （余裕 ${slack.toFixed(2)} mm）</p>
  `;

  resultTableBody.innerHTML = '';
  rolls.forEach((rollCount, index) => {
    const row = document.createElement('tr');
    const producedValue = produced[index] ?? 0;
    const differenceValue = differences[index] ?? 0;
    row.innerHTML = `
      <td>${index + 1}</td>
      <td>${payload.widths[index].toFixed(2)}</td>
      <td>${rollCount}</td>
      <td>${producedValue.toFixed(2)}</td>
      <td>${payload.instructions[index].toFixed(2)}</td>
      <td>${differenceValue.toFixed(2)}</td>
    `;
    resultTableBody.appendChild(row);
  });

  resultSection.hidden = false;
}

function showError(message) {
  errorMessage.textContent = message;
  errorSection.hidden = false;
}

function hideError() {
  errorSection.hidden = true;
  errorMessage.textContent = '';
}

function hideResult() {
  resultSection.hidden = true;
  resultTableBody.innerHTML = '';
  resultSummary.innerHTML = '';
}

form.addEventListener('submit', submitForm);
addRowButton.addEventListener('click', () => addSlitRow());

addSlitRow();
addSlitRow();
