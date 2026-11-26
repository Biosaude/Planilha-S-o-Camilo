import os
import time
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import streamlit as st

from src.material_matcher import review_warnings
from src.models import QuoteError
from src.security import ROLES, local_role, oidc_role
from src.settings import audit_path, database_path
from src.tuss_importer import FILENAMES, import_bases, list_versions, restore_version
from src.workflow import analyze, generate

TITLE = 'Automação de Cotações OPME — Hospital São Camilo'
MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
WAIT = 1.0


def _authenticate():
    mode = os.environ.get('BIOSAUDE_AUTH_MODE', 'local')
    if mode == 'public':
        # Acesso direto exclusivamente ao fluxo de cotacao. Nunca concede privilegios de administrador.
        if 'public_identity' not in st.session_state:
            st.session_state.public_identity = f'public:{uuid4().hex}'
        return st.session_state.public_identity, 'operador'
    if mode == 'oidc':
        if not st.user.is_logged_in:
            if st.button('Entrar com a conta institucional', type='primary'):
                st.login()
            st.stop()
        subject = str(st.user.get('sub', ''))
        role = oidc_role(subject)
        if not role:
            st.error('Sua conta não tem acesso a este sistema.')
            if st.button('Sair'):
                st.logout()
            st.stop()
        return subject, role
    if mode != 'local':
        st.error('Modo de autenticação inválido. Avise a administração.')
        st.stop()
    if 'identity' not in st.session_state:
        with st.form('login', clear_on_submit=True):
            profile = st.radio('Perfil', ROLES, format_func=str.capitalize, horizontal=True)
            password = st.text_input('Senha', type='password', max_chars=1024)
            submitted = st.form_submit_button('Entrar', type='primary')
        if submitted:
            now = time.monotonic()
            if now - st.session_state.get('last_attempt', -WAIT) < WAIT:
                st.warning('Aguarde um instante para tentar novamente.')
                st.stop()
            st.session_state.last_attempt = now
            try:
                if local_role(password, profile):
                    st.session_state.identity = (f'local:{uuid4().hex}', profile)
                    st.rerun()
                st.error('Credenciais inválidas.')
            except QuoteError as exc:
                st.error(str(exc))
        st.stop()
    return st.session_state.identity


def _logout():
    st.session_state.clear()
    if os.environ.get('BIOSAUDE_AUTH_MODE') == 'oidc':
        st.logout()
    st.rerun()


def _payload(upload):
    return upload.getvalue(), upload.name


def _clear_analysis():
    for key in tuple(st.session_state.keys()):
        if key in {'analysis', 'generated'} or key.startswith('review_'):
            del st.session_state[key]


def _brl(number: Decimal):
    return 'R$ ' + f'{number:,.2f}'.translate(str.maketrans(',.', '.,'))


def _review(analysis):
    st.subheader('Conferência')
    automatic = {match.row.number for match in analysis.matches if match.row}
    decisions = {}
    table = []
    pending = 0
    for index, (product, match, tuss) in enumerate(
        zip(analysis.quote.products, analysis.matches, analysis.tuss, strict=True)
    ):
        row = match.row.number if match.row else None
        state = 'Confirmado' if row else 'Revisão necessária' if match.candidates else 'Não localizado'
        table.append({
            'Referência PDF': product.reference or '—', 'Linha Excel': str(row) if row else '—',
            'Descrição': product.description, 'Marca': product.brand, 'ANVISA': product.anvisa,
            'Quantidade': format(product.quantity, 'f'), 'Unitário': _brl(product.unit),
            'Total': _brl(product.total), 'Código TUSS': tuss.code or '—',
            'Correspondência': state,
            'Situação TUSS': 'Preenchido automaticamente' if tuss.code else 'Em branco',
        })
        pending += not bool(row)
    overview = st.container()

    for index, (product, match, tuss) in enumerate(
        zip(analysis.quote.products, analysis.matches, analysis.tuss, strict=True)
    ):
        if match.row:
            continue
        key = 'review_' + analysis.key + '_' + str(index)
        with st.expander(f'{product.reference or f"Item {index + 1}"} · {product.description}'):
            if not match.row:
                compatible = [row for row in analysis.hospital.rows if row.number not in automatic
                              and (row.quantity is None or row.quantity == product.quantity)]
                by_number = {row.number: row for row in compatible}
                candidates = [row for row in match.candidates if row.number in by_number]
                if candidates:
                    st.dataframe([
                        {'Linha': row.number, 'Material solicitado': row.description}
                        for row in candidates
                    ], width='stretch', hide_index=True)
                action = st.radio('Decisão para este item', ['Pendente', 'Confirmar linha', 'Omitir item'],
                                  horizontal=True, key=key)
                if action == 'Confirmar linha':
                    selected = st.number_input('Linha do Excel', min_value=1, max_value=20_000,
                                               value=None, key=f'{key}_line')
                    if selected is not None:
                        if selected not in by_number:
                            st.error('Selecione uma linha disponível, do material e da quantidade a conferir.')
                        else:
                            selected_row = by_number[selected]
                            st.write(f'Linha {selected} · {selected_row.description}')
                            warnings = review_warnings(product, selected_row)
                            if warnings:
                                st.warning('Confira com o hospital: ' + ' · '.join(warnings))
                            if st.checkbox('Confirmo a equivalência técnica desta linha',
                                           key=f'{key}_confirm_{selected}'):
                                decisions[index] = selected
                                table[index]['Linha Excel'] = str(selected)
                                table[index]['Correspondência'] = 'Confirmado manualmente'
                elif action == 'Omitir item':
                    decisions[index] = None
                    table[index]['Correspondência'] = 'Omitido manualmente'
    with overview:
        st.dataframe(table, width='stretch', hide_index=True)
        st.caption(f'Total do PDF {_brl(sum(product.total for product in analysis.quote.products))} · '
                   f'Base TUSS, versão {analysis.catalog_version}')
    return decisions, pending


def _operation(identity):
    x, y = st.columns(2)
    with x:
        excel = st.file_uploader('Planilha original do Hospital São Camilo', type='xlsx', key='hospital_excel',
                                 on_change=_clear_analysis)
    with y:
        pdf = st.file_uploader('Orçamento Biosaúde · VS|OPME', type='pdf', key='quote_pdf', on_change=_clear_analysis)
    if st.button('Processar cotação', type='primary', disabled=not (excel and pdf)):
        _clear_analysis()
        try:
            with st.spinner('Extraindo itens, verificando linhas e consultando o catálogo TUSS'):
                st.session_state.analysis = analyze(_payload(excel), _payload(pdf), database_path())
        except QuoteError as exc:
            st.error(str(exc))
    analysis = st.session_state.get('analysis')
    if not analysis:
        return
    decisions, pending = _review(analysis)
    selection = (analysis.key, tuple(decisions.items()))
    selected_rows = [match.row.number for match in analysis.matches if match.row]
    selected_rows.extend(row for row in decisions.values() if row is not None)
    conflicts = len(selected_rows) != len(set(selected_rows))
    if conflicts:
        st.error('Uma linha foi selecionada para mais de um item. Revise as seleções.')
    elif len(decisions) != pending:
        st.info(f'Revise ou omita os {pending - len(decisions)} itens pendentes para habilitar a exportação.')
    missing_codes = sum(not analysis.tuss[i].code for i, match in enumerate(analysis.matches)
                        if match.row or decisions.get(i) is not None)
    if selected_rows:
        st.info(f'TUSS: {len(selected_rows) - missing_codes} itens preenchidos automaticamente; '
                f'{missing_codes} itens ficarão com TUSS em branco.')
    if st.button('Preparar planilha para download', disabled=conflicts or len(decisions) != pending or not selected_rows):
        st.session_state.pop('generated', None)
        try:
            with st.spinner('Validando a preservação do Excel'):
                result = generate(_payload(excel), analysis, decisions, audit_path(), *identity)
            st.session_state.generated = (selection, result)
        except QuoteError as exc:
            st.error(str(exc))
    generated = st.session_state.get('generated')
    if generated and generated[0] == selection:
        st.download_button('Baixar planilha preenchida', generated[1], 'cotacao-sao-camilo-preenchida.xlsx',
                           mime=MIME, type='primary')


def _administration():
    st.subheader('Catálogo TUSS')
    try:
        active, versions = list_versions(database_path())
    except QuoteError as exc:
        st.error(str(exc))
        return
    if versions:
        st.dataframe([{
            'Versão': report.id, 'Nome': report.label, 'Ativa': report.id == active,
            'Importação UTC': datetime.fromisoformat(report.imported_at).strftime('%d/%m/%Y %H:%M'),
            'Parte 1': report.count1, 'Parte 2': report.count2, 'ANVISA em vários códigos': report.shared_anvisa,
            'ANVISA inválidos': report.invalid_anvisa, 'Registros repetidos': report.duplicate_records,
        } for report in versions], hide_index=True, width='stretch')
    else:
        st.info('Importe as duas partes para habilitar a consulta TUSS.')
    with st.form('import', clear_on_submit=True):
        label = st.text_input('Nome da nova versão', max_chars=80)
        part1, part2 = [st.file_uploader(f'Parte {index} · {file}', type='xlsx', key=f'part{index}')
                        for index, file in enumerate(FILENAMES, 1)]
        submitted = st.form_submit_button('Validar e ativar nova versão', type='primary')
    if submitted:
        if not part1 or not part2:
            st.error('Selecione as duas planilhas TUSS.')
        else:
            try:
                with st.spinner('Validando e importando as duas bases'):
                    report = import_bases(database_path(), _payload(part1), _payload(part2), label)
                st.session_state.admin_notice = (f'Versão {report.id} ativada. '
                                                 f'{report.count1:,} registros na parte 1 e {report.count2:,} na parte 2.'
                                                 .replace(',', '.'))
                st.rerun()
            except QuoteError as exc:
                st.error(str(exc))
    previous = [version for version in versions if version.id != active]
    if previous:
        with st.form('restore'):
            choice = st.selectbox('Restaurar versão anterior', previous, format_func=lambda v: f'{v.id} · {v.label}')
            if st.form_submit_button('Reativar versão'):
                try:
                    restore_version(database_path(), choice.id)
                    st.session_state.admin_notice = f'Versão {choice.id} reativada.'
                    st.rerun()
                except QuoteError as exc:
                    st.error(str(exc))
    if notice := st.session_state.pop('admin_notice', None):
        st.success(notice)


st.set_page_config(page_title=TITLE, layout='wide')
st.caption('BIOSAÚDE PRODUTOS HOSPITALARES')
st.title(TITLE)
identity = _authenticate()
if os.environ.get('BIOSAUDE_AUTH_MODE', 'local') != 'public':
    if st.sidebar.button('Sair', width='stretch'):
        _logout()
if identity[1] == 'administrador':
    section = st.sidebar.radio('Área', ['Cotação', 'Catálogo TUSS'])
    if section == 'Catálogo TUSS':
        _administration()
    else:
        _operation(identity)
else:
    _operation(identity)
