from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
import math

app = Flask(__name__)
app.secret_key = 'super_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# =======================
# DATABASE MODELS
# =======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(10), nullable=False) # 'admin' or 'user'

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

class Warehouse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    qty = db.Column(db.Integer, nullable=False)
    warehouse = db.relationship('Warehouse', backref='stocks')
    product = db.relationship('Product', backref='stocks')

class Request(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    qty = db.Column(db.Integer, nullable=False)
    user_lat = db.Column(db.Float, nullable=False)
    user_lon = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='Pending') # Pending, Approved, Rejected
    assigned_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=True)
    eta_days = db.Column(db.Integer, nullable=True)
    
    product = db.relationship('Product')
    warehouse = db.relationship('Warehouse')

# =======================
# HELPER: DISTANCE LOGIC
# =======================
def haversine(lat1, lon1, lat2, lon2):
    # Calculates distance between two points on Earth in kilometers
    R = 6371 
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# =======================
# ROUTES
# =======================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username'], password=request.form['password']).first()
        if user:
            session['user_id'] = user.id
            session['role'] = user.role
            return redirect(url_for('admin_dashboard' if user.role == 'admin' else 'user_dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/user', methods=['GET', 'POST'])
def user_dashboard():
    if session.get('role') != 'user': return redirect(url_for('login'))
    
    if request.method == 'POST':
        new_req = Request(
            user_id=session['user_id'],
            product_id=request.form['product_id'],
            qty=request.form['qty'],
            user_lat=request.form['lat'],
            user_lon=request.form['lon']
        )
        db.session.add(new_req)
        db.session.commit()
        flash('Request submitted successfully!')

    products = Product.query.all()
    requests = Request.query.filter_by(user_id=session['user_id']).all()
    return render_template('user_dashboard.html', products=products, requests=requests)

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    requests = Request.query.filter_by(status='Pending').all()
    return render_template('admin_dashboard.html', requests=requests)

@app.route('/process/<int:req_id>')
def process_request(req_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    req = Request.query.get(req_id)
    # Find warehouses with enough stock for this product
    available_stocks = Stock.query.filter_by(product_id=req.product_id).filter(Stock.qty >= req.qty).all()
    
    if not available_stocks:
        req.status = 'Rejected (No Stock)'
        db.session.commit()
        flash(f'Request #{req.id} rejected. Not enough stock anywhere.')
        return redirect(url_for('admin_dashboard'))

    nearest_stock = None
    min_dist = float('inf')

    # Find the nearest one
    for stock in available_stocks:
        dist = haversine(req.user_lat, req.user_lon, stock.warehouse.lat, stock.warehouse.lon)
        if dist < min_dist:
            min_dist = dist
            nearest_stock = stock

    # Approve and Assign
    req.status = 'Approved'
    req.assigned_warehouse_id = nearest_stock.warehouse.id
    req.eta_days = max(1, int(min_dist / 100)) # Mock ETA: 1 day per 100km
    
    # Deduct stock
    nearest_stock.qty -= req.qty
    db.session.commit()
    
    flash(f'Request #{req.id} approved! Assigned to {nearest_stock.warehouse.name} ({min_dist:.1f} km away).')
    return redirect(url_for('admin_dashboard'))

# =======================
# INIT DUMMY DATA
# =======================
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.first():
            # Create Users
            db.session.add(User(username='admin', password='123', role='admin'))
            db.session.add(User(username='user1', password='123', role='user'))
            
            # Create Products
            p1 = Product(name='Laptops')
            p2 = Product(name='Monitors')
            db.session.add_all([p1, p2])
            db.session.commit()

            # Create Warehouses (Using rough US coordinates for example)
            w1 = Warehouse(name='New York Hub', lat=40.71, lon=-74.00)
            w2 = Warehouse(name='Los Angeles Hub', lat=34.05, lon=-118.24)
            db.session.add_all([w1, w2])
            db.session.commit()

            # Add Stock (NY has 10 Laptops, LA has 50 Laptops)
            db.session.add(Stock(warehouse_id=w1.id, product_id=p1.id, qty=10))
            db.session.add(Stock(warehouse_id=w2.id, product_id=p1.id, qty=50))
            db.session.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)