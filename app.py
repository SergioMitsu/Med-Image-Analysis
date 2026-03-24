import os
import uuid
import json
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

# Banco de dados SQLite
data_dir = os.environ.get('DATA_DIR', '.')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{data_dir}/database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Upload de imagens
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
# ANALISADOR SIMPLES (para teste)
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
@app.route('/profile')
@login_required
def profile():
    """Página de perfil do usuário"""
    return render_template('profile.html', user=current_user)
    
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
    return render_template('dashboard.html', total_analises=total, analises_anomalia=anomalias, ultimas_analises=ultimas)

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
            flash('Formato não permitido!', 'danger')
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
        except Exception as e:
            flash(f'Erro: {str(e)}', 'danger')
    
    return render_template('upload.html')

@app.route('/results')
@login_required
def results():
    resultado = session.get('ultimo_resultado')
    if not resultado:
        return redirect(url_for('upload'))
    return render_template('results.html', resultado=resultado)

@app.route('/history')
@login_required
def history():
    analises = Analise.query.filter_by(user_id=current_user.id).order_by(Analise.created_at.desc()).all()
    return render_template('history.html', analises=analises)

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Acesso negado!', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('admin_dashboard.html',
                         total_usuarios=User.query.count(),
                         total_analises=Analise.query.count())

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
