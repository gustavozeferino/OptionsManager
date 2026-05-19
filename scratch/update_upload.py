import os

with open('dadosb3/templates/dadosb3/upload.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update buttons
content = content.replace(
'''            <div class="d-flex gap-2">
                <button id="btnConsolidar" class="btn btn-outline-secondary d-flex align-items-center">
                    <i class="fas fa-compress-arrows-alt me-2"></i> Consolidar Negócios
                </button>
                <button id="btnSincronizar" class="btn btn-outline-secondary d-flex align-items-center">
                    <i class="fas fa-sync-alt me-2"></i> Sincronizar Histórico
                </button>
            </div>''',
'''            <div class="d-flex gap-2">
                <button type="button" class="btn btn-outline-secondary d-flex align-items-center" data-bs-toggle="modal" data-bs-target="#dateModal" data-action="consolidar">
                    <i class="fas fa-compress-arrows-alt me-2"></i> Consolidar Negócios
                </button>
                <button type="button" class="btn btn-outline-secondary d-flex align-items-center" data-bs-toggle="modal" data-bs-target="#dateModal" data-action="sincronizar">
                    <i class="fas fa-sync-alt me-2"></i> Sincronizar base de trading
                </button>
            </div>'''
)

# 2. Add Modal before scripts
modal_html = '''
    <!-- Date Modal -->
    <div class="modal fade" id="dateModal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content rounded-4 border-0 shadow-lg">
          <div class="modal-header bg-light border-bottom-0">
            <h5 class="modal-title fw-bold" id="dateModalLabel">Configurar Execução</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body p-4">
            <p class="text-muted small mb-4">Escolha a data inicial. A rotina processará os dados dia-a-dia a partir dessa data.</p>
            
            <div class="form-check form-switch mb-4">
              <input class="form-check-input" type="checkbox" id="chkTodosDias" role="switch">
              <label class="form-check-label fw-bold text-primary ms-2" for="chkTodosDias">
                Selecionar Todos os Dias (Recálculo total)
              </label>
            </div>
            
            <div class="mb-3" id="divDataInput">
                <label for="dataInicioRotina" class="form-label fw-bold">Data Inicial:</label>
                <input type="date" class="form-control form-control-lg bg-light" id="dataInicioRotina">
            </div>
          </div>
          <div class="modal-footer border-top-0 bg-light rounded-bottom-4">
            <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
            <button type="button" class="btn btn-primary px-4" id="btnConfirmarRotina">
                <span id="btnConfirmarText">Executar Rotina</span>
                <i id="btnConfirmarSpinner" class="fas fa-circle-notch fa-spin ms-2 d-none"></i>
            </button>
          </div>
        </div>
      </div>
    </div>
</div>

<script>'''

content = content.replace('</div>\n\n<script>', modal_html)

# 3. Update JavaScript logic
old_js = '''    btnConsolidar.addEventListener('click', () => {
        const icon = btnConsolidar.querySelector('i');
        icon.classList.remove('fa-compress-arrows-alt');
        icon.classList.add('fa-circle-notch', 'fa-spin');
        fetch('{% url "dadosb3:admin_consolidar" %}', {
            method: 'POST',
            headers: {'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value}
        }).then(r => r.json()).then(data => {
            alert(data.message);
            loadStats();
        }).finally(() => {
            icon.classList.add('fa-compress-arrows-alt');
            icon.classList.remove('fa-circle-notch', 'fa-spin');
        });
    });
    
    btnSincronizar.addEventListener('click', () => {
        const icon = btnSincronizar.querySelector('i');
        icon.classList.remove('fa-sync-alt');
        icon.classList.add('fa-circle-notch', 'fa-spin');
        fetch('{% url "dadosb3:admin_sincronizar" %}', {
            method: 'POST',
            headers: {'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value}
        }).then(r => r.json()).then(data => {
            alert(data.message);
        }).finally(() => {
            icon.classList.add('fa-sync-alt');
            icon.classList.remove('fa-circle-notch', 'fa-spin');
        });
    });'''

new_js = '''
    const chkTodosDias = document.getElementById('chkTodosDias');
    const divDataInput = document.getElementById('divDataInput');
    const dataInicioRotina = document.getElementById('dataInicioRotina');
    const btnConfirmarRotina = document.getElementById('btnConfirmarRotina');
    const dateModalEl = document.getElementById('dateModal');
    let dateModal = null;
    let currentAction = null;
    let currentTaskName = '';
    const unitLabel = document.getElementById('unitLabel') || {textContent: 'linhas'};

    if (typeof bootstrap !== 'undefined') {
        dateModal = new bootstrap.Modal(dateModalEl);
    }
    
    dateModalEl.addEventListener('show.bs.modal', function (event) {
        const button = event.relatedTarget;
        currentAction = button.getAttribute('data-action');
        currentTaskName = currentAction === 'consolidar' ? 'Consolidação' : 'Sincronização';
        document.getElementById('dateModalLabel').textContent = 'Configurar ' + currentTaskName;
        chkTodosDias.checked = false;
        divDataInput.style.opacity = '1';
        divDataInput.style.pointerEvents = 'auto';
        dataInicioRotina.value = '';
    });
    
    chkTodosDias.addEventListener('change', (e) => {
        if(e.target.checked) {
            divDataInput.style.opacity = '0.5';
            divDataInput.style.pointerEvents = 'none';
        } else {
            divDataInput.style.opacity = '1';
            divDataInput.style.pointerEvents = 'auto';
        }
    });

    btnConfirmarRotina.addEventListener('click', () => {
        const isAll = chkTodosDias.checked;
        const dataSelecionada = dataInicioRotina.value;
        
        if (!isAll && !dataSelecionada) {
            alert('Por favor, selecione uma data inicial ou marque "Todos os dias".');
            return;
        }

        const dateVal = isAll ? 'ALL' : dataSelecionada;
        
        const btnText = document.getElementById('btnConfirmarText');
        const btnSpinner = document.getElementById('btnConfirmarSpinner');
        btnText.textContent = 'Iniciando...';
        btnSpinner.classList.remove('d-none');
        btnConfirmarRotina.disabled = true;

        const url = currentAction === 'consolidar' ? '{% url "dadosb3:admin_consolidar" %}' : '{% url "dadosb3:admin_sincronizar" %}';
        
        const formData = new FormData();
        formData.append('data_inicio', dateVal);

        fetch(url, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            }
        })
        .then(r => r.json())
        .then(data => {
            if(data.status === 'success' && data.task_id) {
                dateModal.hide();
                startTelemetryForRoutine(data.task_id, currentTaskName);
            } else {
                alert(data.message || 'Erro ao iniciar a rotina.');
            }
        })
        .catch(err => {
            alert('Erro ao se conectar com o servidor.');
        })
        .finally(() => {
            btnText.textContent = 'Executar Rotina';
            btnSpinner.classList.add('d-none');
            btnConfirmarRotina.disabled = false;
        });
    });

    function startTelemetryForRoutine(taskId, taskName) {
        telemetryPanel.classList.remove('d-none');
        summaryPanel.classList.add('d-none');
        
        progressBar.style.width = '0%';
        progressBar.classList.remove('bg-danger', 'bg-success');
        progressBar.classList.add('bg-primary');
        progressPercentage.textContent = '0%';
        statusLabel.textContent = `Executando ${taskName}...`;
        
        checkProgress(taskId);
    }
'''

content = content.replace(old_js, new_js)

content = content.replace('<span id="linesTotal" class="text-muted">?</span> <small>linhas</small>',
                          '<span id="linesTotal" class="text-muted">?</span> <small id="unitLabel">linhas</small>')
content = content.replace('<span id="speedIndicator" class="fs-4 fw-mono">0</span> <small>reg/s</small>',
                          '<span id="speedIndicator" class="fs-4 fw-mono">0</span> <small id="speedUnitLabel">reg/s</small>')

old_check = 'if (data.stats) {'
new_check = '''if (data.stats) {
                        if (data.stats.unit) {
                            document.getElementById('unitLabel').textContent = data.stats.unit;
                            document.getElementById('speedUnitLabel').textContent = data.stats.unit + '/s';
                        } else {
                            document.getElementById('unitLabel').textContent = 'linhas';
                            document.getElementById('speedUnitLabel').textContent = 'linhas/s';
                        }'''
content = content.replace(old_check, new_check)

with open('dadosb3/templates/dadosb3/upload.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('upload.html modified successfully.')
