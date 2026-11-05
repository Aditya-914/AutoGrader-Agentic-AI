/**
 * AutoGrader Code Editor Controller
 * Handles line numbering, indentation (Tab/Enter), and synchronization.
 */

class CodeEditor {
  constructor(textareaId, lineNumbersId, statusLineId) {
    this.textarea = document.getElementById(textareaId);
    this.lineNumbers = document.getElementById(lineNumbersId);
    this.statusLine = document.getElementById(statusLineId);

    if (!this.textarea || !this.lineNumbers) return;

    this.initEvents();
    this.updateLineNumbers();
    this.updateStatus();
  }

  initEvents() {
    // Synchronize scrolling between textarea and line numbers
    this.textarea.addEventListener('scroll', () => {
      this.lineNumbers.scrollTop = this.textarea.scrollTop;
    });

    // Update lines on input
    this.textarea.addEventListener('input', () => {
      this.updateLineNumbers();
      this.updateStatus();
    });

    // Handle key combinations (Tab indentation & Enter auto-indent)
    this.textarea.addEventListener('keydown', (e) => {
      if (e.key === 'Tab') {
        e.preventDefault();
        this.handleTab(e.shiftKey);
      } else if (e.key === 'Enter') {
        this.handleEnter(e);
      }
    });

    this.textarea.addEventListener('click', () => this.updateStatus());
    this.textarea.addEventListener('keyup', () => this.updateStatus());
  }

  updateLineNumbers() {
    const lines = this.textarea.value.split('\n').length;
    let numbersHtml = '';
    for (let i = 1; i <= Math.max(lines, 1); i++) {
      numbersHtml += `<div>${i}</div>`;
    }
    this.lineNumbers.innerHTML = numbersHtml;
  }

  updateStatus() {
    if (!this.statusLine) return;
    const val = this.textarea.value;
    const lines = val.split('\n').length;
    const chars = val.length;

    // Calculate cursor line & col
    const cursor = this.textarea.selectionStart;
    const linesBefore = val.substring(0, cursor).split('\n');
    const currentLine = linesBefore.length;
    const currentCol = linesBefore[linesBefore.length - 1].length + 1;

    this.statusLine.textContent = `Ln ${currentLine}, Col ${currentCol}  |  ${lines} lines  |  ${chars} chars  |  C (C11 standard)`;
  }

  handleTab(isShift) {
    const start = this.textarea.selectionStart;
    const end = this.textarea.selectionEnd;
    const value = this.textarea.value;

    if (!isShift) {
      // Insert 4 spaces
      this.textarea.value = value.substring(0, start) + '    ' + value.substring(end);
      this.textarea.selectionStart = this.textarea.selectionEnd = start + 4;
    } else {
      // Dedent 4 spaces if possible
      const lineStart = value.lastIndexOf('\n', start - 1) + 1;
      const leadingSpaces = value.substring(lineStart, lineStart + 4);
      if (leadingSpaces === '    ') {
        this.textarea.value = value.substring(0, lineStart) + value.substring(lineStart + 4);
        this.textarea.selectionStart = this.textarea.selectionEnd = Math.max(lineStart, start - 4);
      }
    }
    this.updateLineNumbers();
    this.updateStatus();
  }

  handleEnter(e) {
    const start = this.textarea.selectionStart;
    const value = this.textarea.value;
    const currentLineStart = value.lastIndexOf('\n', start - 1) + 1;
    const currentLine = value.substring(currentLineStart, start);
    
    // Find leading whitespace
    const match = currentLine.match(/^(\s+)/);
    let indent = match ? match[1] : '';

    // If the line ended with an opening brace, add extra indent
    if (currentLine.trim().endsWith('{')) {
      e.preventDefault();
      indent += '    ';
      this.textarea.value = value.substring(0, start) + '\n' + indent + value.substring(start);
      this.textarea.selectionStart = this.textarea.selectionEnd = start + 1 + indent.length;
      this.updateLineNumbers();
      this.updateStatus();
    } else if (indent) {
      e.preventDefault();
      this.textarea.value = value.substring(0, start) + '\n' + indent + value.substring(start);
      this.textarea.selectionStart = this.textarea.selectionEnd = start + 1 + indent.length;
      this.updateLineNumbers();
      this.updateStatus();
    }
  }

  getValue() {
    return this.textarea.value;
  }

  setValue(code) {
    this.textarea.value = code;
    this.updateLineNumbers();
    this.updateStatus();
  }

  clear() {
    this.setValue('');
  }
}

window.CodeEditor = CodeEditor;
