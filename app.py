import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import numpy as np
from PIL import Image
import io

# ============================================
# CONFIGURAÇÃO
# ============================================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chave-secreta-padrao')

data_dir = os.environ.get('DATA_DIR', '.')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{data_dir}/database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(data_dir, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ============================================
# BANCO DE DADOS
# ============================================
db = SQLAlchemy(app)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='paciente')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    analises = db.relationship('Analise', backref='user', lazy=True)

class Analise(db.Model):
    __tablename__ = 'analises'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    filepath = db.Column(db.String(500), nullable=False)
    resultado = db.Column(db.String(20), nullable=False)
    probabilidade = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============================================
# ANALISADOR SIMPLES
# ============================================
class ImageAnalyzer:
    def analisar(self, imagem_bytes):
        try:
            image = Image.open(io.BytesIO(imagem_bytes))
            if image.mode != 'L':
                image = image.convert('L')
            image = image.resize((128, 128))
            img_array = np.array(image)
            
            media = np.mean(img_array)
            desvio = np.std(img_array)
            score = (media / 255) * 0.5 + (desvio / 128) * 0.5
            
            if score < 0.45:
                resultado = 'ANOMALIA'
                probabilidade = score
            else:
                resultado = 'NORMAL'
                probabilidade = 1 - score
            
            return {'sucesso': True, 'resultado': resultado, 'probabilidade': probabilidade}
        except Exception as e:
            return {'sucesso': False, 'mensagem': str(e)}

analyzer = ImageAnalyzer()

# ============================================
# AUTENTICAÇÃO
# ============================================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ============================================
# ROTAS
# ============================================
@app.route('/admin/relatorio-pdf')
@login_required
def gerar_relatorio_pdf():
    """Gera relatório PDF com estatísticas do sistema (apenas admin)"""
    if current_user.role != 'admin':
        flash('Acesso negado!', 'danger')
        return redirect(url_for('dashboard'))
    
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as ReportImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER
    import io
    from datetime import datetime
    import matplotlib.pyplot as plt
    
    # Criar buffer para o PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []
    
    # Título
    titulo_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#667eea'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    story.append(Paragraph("MedAnalyzer - Relatório do Sistema", titulo_style))
    story.append(Spacer(1, 20))
    
    # Data do relatório
    data_atual = datetime.now().strftime('%d/%m/%Y %H:%M')
    story.append(Paragraph(f"Gerado em: {data_atual}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Estatísticas gerais
    total_usuarios = User.query.count()
    total_analises = Analise.query.count()
    normais = Analise.query.filter_by(resultado='NORMAL').count()
    anomalias = Analise.query.filter_by(resultado='ANOMALIA').count()
    taxa_anomalias = (anomalias / total_analises * 100) if total_analises > 0 else 0
    
    stats_data = [
        ['Métrica', 'Valor'],
        ['Total de Usuários', str(total_usuarios)],
        ['Total de Análises', str(total_analises)],
        ['Análises Normais', str(normais)],
        ['Análises com Anomalia', str(anomalias)],
        ['Taxa de Anomalias', f'{taxa_anomalias:.1f}%']
    ]
    
    tabela_stats = Table(stats_data, colWidths=[8*cm, 6*cm])
    tabela_stats.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(tabela_stats)
    story.append(Spacer(1, 30))
    
    # Gráfico de pizza (proporção)
    fig, ax = plt.subplots(figsize=(6, 4))
    labels = ['NORMAL', 'ANOMALIA']
    sizes = [normais, anomalias]
    colors_list = ['#28a745', '#dc3545']
    ax.pie(sizes, labels=labels, colors=colors_list, autopct='%1.1f%%', startangle=90)
    ax.set_title('Proporção de Resultados')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    img = ReportImage(buf, width=10*cm, height=8*cm)
    story.append(img)
    story.append(Spacer(1, 20))
    
    # Lista de usuários
    story.append(Paragraph("Usuários Cadastrados", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    usuarios = User.query.all()
    usuarios_data = [['ID', 'Usuário', 'Email', 'Papel', 'Análises']]
    for u in usuarios:
        num_analises = Analise.query.filter_by(user_id=u.id).count()
        usuarios_data.append([str(u.id), u.username, u.email, u.role, str(num_analises)])
    
    tabela_usuarios = Table(usuarios_data, colWidths=[2*cm, 4*cm, 6*cm, 3*cm, 2*cm])
    tabela_usuarios.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER')
    ]))
    story.append(tabela_usuarios)
    
    # Construir PDF
    doc.build(story)
    buffer.seek(0)
    
    # Enviar PDF para download
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'relatorio_medanalyzer_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf',
        mimetype='application/pdf'
    )

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash(f'Bem-vindo, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Usuário ou senha inválidos!', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'paciente')
        
        if User.query.filter_by(username=username).first():
            flash('Usuário já existe!', 'danger')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email já cadastrado!', 'danger')
            return redirect(url_for('register'))
        
        user = User(
            username=username,
            email=email,
            password=generate_password_hash(password),
            role=role
        )
        db.session.add(user)
        db.session.commit()
        flash('Cadastro realizado! Faça login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    total = Analise.query.filter_by(user_id=current_user.id).count()
    anomalias = Analise.query.filter_by(user_id=current_user.id, resultado='ANOMALIA').count()
    ultimas = Analise.query.filter_by(user_id=current_user.id).order_by(Analise.created_at.desc()).limit(5).all()
    
    # ============================================
    # DADOS PARA GRÁFICOS (apenas para admin)
    # ============================================
    dados_graficos = None
    if current_user.role == 'admin':
        # Total de análises por dia (últimos 7 dias)
        from datetime import datetime, timedelta
        import matplotlib.pyplot as plt
        import io
        import base64
        
        dados_por_dia = []
        datas = []
        for i in range(7):
            data = datetime.now() - timedelta(days=i)
            dia_inicio = datetime(data.year, data.month, data.day, 0, 0, 0)
            dia_fim = datetime(data.year, data.month, data.day, 23, 59, 59)
            total_dia = Analise.query.filter(Analise.created_at >= dia_inicio, Analise.created_at <= dia_fim).count()
            dados_por_dia.append(total_dia)
            datas.append(data.strftime('%d/%m'))
        
        # Total de análises por usuário (top 5)
        from sqlalchemy import func
        top_usuarios = db.session.query(User.username, func.count(Analise.id))\
            .join(Analise, User.id == Analise.user_id)\
            .group_by(User.id)\
            .order_by(func.count(Analise.id).desc())\
            .limit(5).all()
        
        usuarios_nomes = [u[0] for u in top_usuarios]
        usuarios_counts = [u[1] for u in top_usuarios]
        
        # Gráfico 1: Análises por dia
        fig1, ax1 = plt.subplots(figsize=(10, 4))
        ax1.bar(datas, dados_por_dia, color='#667eea')
        ax1.set_title('Análises por Dia (Últimos 7 Dias)', fontsize=14, fontweight='bold')
        ax1.set_xlabel('Data')
        ax1.set_ylabel('Número de Análises')
        ax1.set_facecolor('#f8f9fa')
        fig1.patch.set_facecolor('#f8f9fa')
        
        # Converte para base64
        buf1 = io.BytesIO()
        fig1.savefig(buf1, format='png', bbox_inches='tight', facecolor='#f8f9fa')
        buf1.seek(0)
        grafico_dias = base64.b64encode(buf1.getvalue()).decode('utf-8')
        plt.close(fig1)
        
        # Gráfico 2: Top usuários
        fig2, ax2 = plt.subplots(figsize=(8, 4))
        cores = ['#667eea', '#764ba2', '#f093fb', '#4facfe', '#00f2fe']
        ax2.barh(usuarios_nomes, usuarios_counts, color=cores)
        ax2.set_title('Top 5 Usuários com Mais Análises', fontsize=14, fontweight='bold')
        ax2.set_xlabel('Número de Análises')
        ax2.set_facecolor('#f8f9fa')
        fig2.patch.set_facecolor('#f8f9fa')
        
        buf2 = io.BytesIO()
        fig2.savefig(buf2, format='png', bbox_inches='tight', facecolor='#f8f9fa')
        buf2.seek(0)
        grafico_usuarios = base64.b64encode(buf2.getvalue()).decode('utf-8')
        plt.close(fig2)
        
        # Gráfico 3: Proporção Normal vs Anomalia
        normais = Analise.query.filter_by(resultado='NORMAL').count()
        anomalias_total = Analise.query.filter_by(resultado='ANOMALIA').count()
        
        fig3, ax3 = plt.subplots(figsize=(6, 6))
        labels = ['NORMAL', 'ANOMALIA']
        sizes = [normais, anomalias_total]
        colors = ['#28a745', '#dc3545']
        explode = (0, 0.1)
        ax3.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%', shadow=True, startangle=90)
        ax3.set_title('Proporção de Resultados', fontsize=14, fontweight='bold')
        
        buf3 = io.BytesIO()
        fig3.savefig(buf3, format='png', bbox_inches='tight')
        buf3.seek(0)
        grafico_pizza = base64.b64encode(buf3.getvalue()).decode('utf-8')
        plt.close(fig3)
        
        dados_graficos = {
            'dias': grafico_dias,
            'usuarios': grafico_usuarios,
            'pizza': grafico_pizza,
            'normais': normais,
            'anomalias': anomalias_total
        }
    
    return render_template('dashboard.html', 
                         total_analises=total, 
                         analises_anomalia=anomalias, 
                         ultimas_analises=ultimas,
                         dados_graficos=dados_graficos,
                         is_admin=(current_user.role == 'admin'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Nenhum arquivo!', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('Nenhum arquivo!', 'danger')
            return redirect(request.url)
        
        if not allowed_file(file.filename):
            flash('Formato não permitido! Use PNG, JPG, JPEG, BMP', 'danger')
            return redirect(request.url)
        
        try:
            filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            with open(filepath, 'rb') as f:
                resultado = analyzer.analisar(f.read())
            
            if resultado['sucesso']:
                analise = Analise(
                    user_id=current_user.id,
                    filename=filename,
                    filepath=filepath,
                    resultado=resultado['resultado'],
                    probabilidade=resultado['probabilidade']
                )
                db.session.add(analise)
                db.session.commit()
                
                session['ultimo_resultado'] = {
                    'resultado': resultado['resultado'],
                    'probabilidade': resultado['probabilidade']
                }
                
                flash(f'Resultado: {resultado["resultado"]}', 'success')
                return redirect(url_for('results'))
            else:
                flash(resultado['mensagem'], 'danger')
        except Exception as e:
            flash(f'Erro: {str(e)}', 'danger')
    
    return render_template('upload.html')

@app.route('/results')
@login_required
def results():
    resultado = session.get('ultimo_resultado')
    if not resultado:
        flash('Nenhuma análise recente.', 'warning')
        return redirect(url_for('upload'))
    return render_template('results.html', resultado=resultado)

@app.route('/history')
@login_required
def history():
    analises = Analise.query.filter_by(user_id=current_user.id).order_by(Analise.created_at.desc()).all()
    return render_template('history.html', analises=analises)

@app.route('/analise/<int:analise_id>')
@login_required
def view_analise(analise_id):
    analise = Analise.query.get_or_404(analise_id)
    if analise.user_id != current_user.id and current_user.role != 'admin':
        flash('Acesso negado!', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('view_analise.html', analise=analise)

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Acesso negado!', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('admin_dashboard.html',
                         total_usuarios=User.query.count(),
                         total_analises=Analise.query.count(),
                         admins=User.query.filter_by(role='admin').count(),
                         medicos=User.query.filter_by(role='medico').count(),
                         pacientes=User.query.filter_by(role='paciente').count(),
                         ultimas_analises=Analise.query.order_by(Analise.created_at.desc()).limit(10).all())

@app.route('/admin/users')
@login_required
def manage_users():
    if current_user.role != 'admin':
        flash('Acesso negado!', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('manage_users.html', usuarios=User.query.all())

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash('Acesso negado!', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    if user.id != current_user.id:
        db.session.delete(user)
        db.session.commit()
        flash(f'Usuário {user.username} deletado!', 'success')
    return redirect(url_for('manage_users'))

# ============================================
# INICIALIZAÇÃO
# ============================================
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            email='admin@sistema.com',
            password=generate_password_hash('admin123'),
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin criado!")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
