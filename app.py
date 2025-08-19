from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from sqlalchemy import func, case
from datetime import datetime, timedelta
from collections import defaultdict
import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# --- CONFIGURAÇÃO ---
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
database_uri = os.environ.get('DATABASE_URL')
if database_uri:
    # A URL do Render começa com 'postgres://', mas o SQLAlchemy espera 'postgresql://'
    if database_uri.startswith("postgres://"):
        database_uri = database_uri.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-segura'

db = SQLAlchemy(app)

# --- INICIALIZE AS NOVAS EXTENSÕES AQUI ---
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login' # Se um usuário não logado tentar acessar uma página protegida, será redirecionado para a rota 'login'
login_manager.login_message_category = 'info' # Categoria da mensagem flash
login_manager.login_message = "Por favor, faça o login para acessar esta página."
# -------------------------------------------

# --- Callback para carregar o usuário da sessão ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --- MODELOS DO BANCO DE DADOS ---

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)

class Licitacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    orgao_cliente = db.Column(db.String(150), nullable=False)
    num_edital = db.Column(db.String(50), nullable=False)
    objeto = db.Column(db.String(300), nullable=False)
    data_abertura = db.Column(db.Date, nullable=False)
    valor_proposta = db.Column(db.Float, nullable=True, default=0.0)
    status = db.Column(db.String(50), nullable=False, default='Em Análise')
    
    produtos = db.relationship('Produto', backref='licitacao', lazy=True, cascade="all, delete-orphan")
    transacoes = db.relationship('Transacao', backref='licitacao', lazy=True)

    @property
    def custo_total(self):
        if not self.produtos:
            return 0.0
        total = sum(p.custo_total for p in self.produtos)
        return float(total) if total is not None else 0.0

    @property
    def lucro_bruto(self):
        valor_prop = self.valor_proposta or 0.0
        return valor_prop - self.custo_total

    @property
    def margem_lucro(self):
        valor_prop = self.valor_proposta or 0.0
        if valor_prop > 0:
            return (self.lucro_bruto / valor_prop) * 100
        return 0.0

class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    custo_unitario = db.Column(db.Float, nullable=False)
    licitacao_id = db.Column(db.Integer, db.ForeignKey('licitacao.id'), nullable=False)

    @property
    def custo_total(self):
        return self.quantidade * self.custo_unitario

class Transacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    descricao = db.Column(db.String(200), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    licitacao_id = db.Column(db.Integer, db.ForeignKey('licitacao.id'), nullable=True)

# --- ROTAS DA APLICAÇÃO ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        # Gera o hash da senha
        hashed_password = bcrypt.generate_password_hash(request.form.get('password')).decode('utf-8')
        user = User(username=request.form.get('username'), password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('Sua conta foi criada! Você já pode fazer o login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        # Verifica se o usuário existe e se a senha corresponde ao hash
        if user and bcrypt.check_password_hash(user.password, request.form.get('password')):
            login_user(user, remember=True)
            next_page = request.args.get('next')
            flash('Login bem-sucedido!', 'success')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('Login falhou. Verifique o usuário e a senha.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- SUAS OUTRAS ROTAS (index, dashboard, etc.) vêm depois ---

@app.route('/')
@login_required 
def index():
    licitacoes = Licitacao.query.order_by(Licitacao.data_abertura.desc()).all()
    saldo_atual = db.session.query(db.func.sum(Transacao.valor)).scalar() or 0.0
    return render_template('index.html', licitacoes=licitacoes, saldo_atual=saldo_atual)

@app.route('/licitacao/add', methods=['POST'])
@login_required
def add_licitacao():
    data_abertura_str = request.form.get('data_abertura')
    nova_licitacao = Licitacao(
        orgao_cliente=request.form.get('orgao_cliente'),
        num_edital=request.form.get('num_edital'),
        objeto=request.form.get('objeto'),
        data_abertura=datetime.strptime(data_abertura_str, '%Y-%m-%d').date()
    )
    db.session.add(nova_licitacao)
    db.session.commit()
    flash('Licitação adicionada com sucesso!', 'success')
    return redirect(url_for('index'))

@app.route('/licitacao/<int:id>')
@login_required
def licitacao_detalhe(id):
    licitacao = Licitacao.query.get_or_404(id)
    return render_template('licitacao_detalhe.html', licitacao=licitacao)

@app.route('/licitacao/<int:id>/update', methods=['POST'])
@login_required
def update_licitacao(id):
    licitacao = Licitacao.query.get_or_404(id)
    status_anterior = licitacao.status
    novo_status = request.form.get('status')
    
    licitacao.valor_proposta = float(request.form.get('valor_proposta', 0))
    licitacao.status = novo_status
    
    if novo_status in ['Perdida', 'Cancelada'] and status_anterior not in ['Perdida', 'Cancelada']:
        debito_original = Transacao.query.filter(Transacao.licitacao_id == id, Transacao.valor < 0).first()
        if debito_original:
            transacao_estorno = Transacao(
                descricao=f"Estorno Custo ({novo_status}) - Edital: {licitacao.num_edital}",
                valor=abs(debito_original.valor),
                licitacao_id=id
            )
            db.session.add(transacao_estorno)
            flash(f"Custo de R$ {abs(debito_original.valor):.2f} estornado ao saldo.", 'success')

    db.session.commit()
    flash('Informações da proposta atualizadas!', 'success')
    return redirect(url_for('licitacao_detalhe', id=id))

@app.route('/licitacao/<int:id>/delete', methods=['POST'])
@login_required
def delete_licitacao(id):
    licitacao = Licitacao.query.get_or_404(id)
    db.session.delete(licitacao)
    db.session.commit()
    flash('Licitação removida com sucesso!', 'danger')
    return redirect(url_for('index'))

@app.route('/licitacao/<int:id>/add_produto', methods=['POST'])
@login_required
def add_produto(id):
    licitacao = Licitacao.query.get_or_404(id)
    novo_produto = Produto(
        descricao=request.form.get('descricao'),
        quantidade=int(request.form.get('quantidade')),
        custo_unitario=float(request.form.get('custo_unitario')),
        licitacao_id=licitacao.id
    )
    db.session.add(novo_produto)
    db.session.commit()
    flash('Produto adicionado à licitação.', 'success')
    return redirect(url_for('licitacao_detalhe', id=id))

@app.route('/produto/<int:id>/delete', methods=['POST'])
@login_required
def delete_produto(id):
    produto = Produto.query.get_or_404(id)
    licitacao_id = produto.licitacao_id
    db.session.delete(produto)
    db.session.commit()
    flash('Produto removido.', 'danger')
    return redirect(url_for('licitacao_detalhe', id=licitacao_id))

@app.route('/licitacao/<int:id>/lancar_custo', methods=['POST'])
@login_required
def lancar_custo(id):
    licitacao = Licitacao.query.get_or_404(id)
    custo = licitacao.custo_total
    
    if custo > 0:
        debito_existente = Transacao.query.filter_by(licitacao_id=id, valor=-custo).first()
        if debito_existente:
            flash('O custo para esta licitação já foi lançado anteriormente.', 'warning')
            return redirect(url_for('licitacao_detalhe', id=id))

        nova_transacao = Transacao(
            descricao=f"Débito Custo Proposta - Edital: {licitacao.num_edital}",
            valor=-custo,
            licitacao_id=id
        )
        db.session.add(nova_transacao)
        licitacao.status = "Participando"
        db.session.commit()
        flash(f'Custo de R$ {custo:.2f} lançado no saldo e status atualizado.', 'info')
    else:
        flash('Não há custos para lançar. Adicione produtos primeiro.', 'warning')
    return redirect(url_for('licitacao_detalhe', id=id))

@app.route('/transacoes')
@login_required
def transacoes():
    todas_as_transacoes = Transacao.query.order_by(Transacao.data.desc()).all()
    saldo_atual = db.session.query(db.func.sum(Transacao.valor)).scalar() or 0.0
    return render_template('transacoes.html', transacoes=todas_as_transacoes, saldo_atual=saldo_atual)

@app.route('/transacao/add', methods=['POST'])
@login_required
def add_transacao():
    valor = float(request.form.get('valor'))
    tipo = request.form.get('tipo')
    
    if tipo == 'debito':
        valor *= -1

    nova_transacao = Transacao(
        descricao=request.form.get('descricao'),
        valor=valor
    )
    db.session.add(nova_transacao)
    db.session.commit()
    flash('Transação registrada com sucesso!', 'success')
    return redirect(url_for('transacoes'))

@app.route('/dashboard')
@login_required
def dashboard():
    # --- 1. PROCESSAR O FILTRO DE DATAS ---
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    # Define um período padrão (ex: este ano) se nenhuma data for fornecida
    today = datetime.utcnow().date()
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    else:
        start_date = today.replace(month=1, day=1) # Início do ano corrente
        
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        end_date = today # Até a data de hoje
    
    # --- 2. APLICAR FILTRO DE DATAS EM TODAS AS CONSULTAS ---
    # Cria uma subconsulta base para aplicar o filtro em todos os cálculos
    licitacoes_no_periodo = Licitacao.query.filter(Licitacao.data_abertura.between(start_date, end_date))
    
    # --- 3. RECALCULAR KPIs COM O FILTRO APLICADO ---
    total_participadas = licitacoes_no_periodo.filter(Licitacao.status.in_(['Vencida', 'Perdida'])).count()
    total_vencidas = licitacoes_no_periodo.filter(Licitacao.status == 'Vencida').count()
    taxa_sucesso = (total_vencidas / total_participadas * 100) if total_participadas > 0 else 0
    faturamento_total = db.session.query(func.sum(Licitacao.valor_proposta)).filter(Licitacao.status == 'Vencida', Licitacao.data_abertura.between(start_date, end_date)).scalar() or 0.0

    licitacoes_vencidas_periodo = licitacoes_no_periodo.filter(Licitacao.status == 'Vencida').all()
    lucro_bruto_total = sum(l.lucro_bruto for l in licitacoes_vencidas_periodo)

    # NOVO KPI: Valor Médio da Proposta Vencida (Ticket Médio)
    valor_medio_proposta = (faturamento_total / total_vencidas) if total_vencidas > 0 else 0.0

    # --- 4. RECALCULAR DADOS DOS GRÁFICOS COM FILTRO ---
    status_counts = licitacoes_no_periodo.with_entities(Licitacao.status, func.count(Licitacao.status)).group_by(Licitacao.status).all()
    funil_labels = [status for status, count in status_counts]
    funil_data = [count for status, count in status_counts]

    faturamento_mensal = defaultdict(float)
    for licitacao in licitacoes_vencidas_periodo:
        mes_ano = licitacao.data_abertura.strftime('%Y-%m')
        faturamento_mensal[mes_ano] += licitacao.valor_proposta or 0.0
    
    meses_ordenados = sorted(faturamento_mensal.keys())
    faturamento_labels = [datetime.strptime(mes, '%Y-%m').strftime('%b/%y') for mes in meses_ordenados]
    faturamento_data = [faturamento_mensal[mes] for mes in meses_ordenados]
    
    desempenho_orgaos = licitacoes_no_periodo.with_entities(
        Licitacao.orgao_cliente, func.count(Licitacao.id)
    ).filter(Licitacao.status == 'Vencida').group_by(Licitacao.orgao_cliente).order_by(func.count(Licitacao.id).desc()).limit(5).all()
    
    orgaos_labels = [orgao for orgao, vitorias in desempenho_orgaos]
    orgaos_data = [vitorias for orgao, vitorias in desempenho_orgaos]
    
    return render_template(
        'dashboard.html',
        # KPIs
        total_participadas=total_participadas,
        total_vencidas=total_vencidas,
        taxa_sucesso=taxa_sucesso,
        faturamento_total=faturamento_total,
        lucro_bruto_total=lucro_bruto_total,
        valor_medio_proposta=valor_medio_proposta, # Passando o novo KPI
        # Dados dos gráficos
        funil_labels=funil_labels, funil_data=funil_data,
        faturamento_labels=faturamento_labels, faturamento_data=faturamento_data,
        orgaos_labels=orgaos_labels, orgaos_data=orgaos_data,
        # Datas do filtro para preencher o formulário
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d')
    )

# --- INICIALIZAÇÃO ---

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)