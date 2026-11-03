const fileInput = document.querySelector('#fileInput');
const fileDrop = document.querySelector('#fileDrop');
const fileName = document.querySelector('#fileName');
const fileMeta = document.querySelector('#fileMeta');
const startButton = document.querySelector('#startButton');
const scanStage = document.querySelector('#scanStage');
const meshStats = document.querySelector('#meshStats');
const viewLabel = document.querySelector('.view-label');
const dialog = document.querySelector('#settingsDialog');

function chooseFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.stl')) {
    fileName.textContent = '文件格式不受支持';
    fileMeta.textContent = '请选择 .stl 文件';
    return;
  }
  const size = file.size > 1024 ** 2
    ? `${(file.size / 1024 ** 2).toFixed(1)} MB`
    : `${(file.size / 1024).toFixed(0)} KB`;
  fileName.textContent = file.name;
  fileMeta.textContent = `${size} · 等待网格检查`;
  meshStats.textContent = `${size.toUpperCase()} · STL MESH`;
  viewLabel.textContent = '文件已就绪';
  scanStage.classList.add('loaded');
  startButton.disabled = false;
}

fileDrop.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => chooseFile(fileInput.files[0]));
['dragenter', 'dragover'].forEach(type => fileDrop.addEventListener(type, event => {
  event.preventDefault();
  fileDrop.classList.add('drag');
}));
['dragleave', 'drop'].forEach(type => fileDrop.addEventListener(type, event => {
  event.preventDefault();
  fileDrop.classList.remove('drag');
}));
fileDrop.addEventListener('drop', event => chooseFile(event.dataTransfer.files[0]));

document.querySelectorAll('input[name="precision"]').forEach(input => {
  input.addEventListener('change', () => {
    document.querySelectorAll('.precision-card').forEach(card => card.classList.remove('active'));
    input.closest('.precision-card').classList.add('active');
  });
});

document.querySelector('#settingsButton').addEventListener('click', () => dialog.showModal());
document.querySelector('#modelButton').addEventListener('click', () => dialog.showModal());
startButton.addEventListener('click', () => {
  startButton.querySelector('span').textContent = '正在检查扫描网格…';
  viewLabel.textContent = '分析中 · 12%';
  startButton.disabled = true;
});
