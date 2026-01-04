from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import os
import json
import asyncio
from pathlib import Path
import sys

# Add parent directory to path to import excel_summary tools
excel_summary_path = Path(__file__).parent.parent / "excel-summary"
sys.path.insert(0, str(excel_summary_path))

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['CHART_FOLDER'] = 'static/charts'

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['CHART_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)

ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Import tools from excel_summary
try:
    # Import the module
    import excel_summary
    
    # Get the async functions
    import_excel = excel_summary.import_excel
    describe_result_summary = excel_summary.describe_result_summary
    render_chart = excel_summary.render_chart
    suggest_charts = excel_summary.suggest_charts
    generate_chart_spec = excel_summary.generate_chart_spec
    
    print("✅ Successfully imported excel_summary tools")
except ImportError as e:
    print(f"❌ Warning: Could not import excel_summary tools: {e}")
    print("Make sure excel-summary dependencies are installed")
    print(f"Trying to import from: {excel_summary_path}")


def run_async(coro):
    """Helper to run async functions"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Read Excel file directly using pandas (more reliable than parsing MCP tool output)
        try:
            import pandas as pd
            import numpy as np
            from datetime import datetime
            
            df = pd.read_excel(filepath)
            
            # Replace NaT, NaN, and other problematic values before converting to dict
            def clean_value(val):
                if pd.isna(val):
                    return None
                elif isinstance(val, (pd.Timestamp, datetime)):
                    # Convert datetime to string
                    return val.isoformat() if pd.notna(val) else None
                elif isinstance(val, (np.integer, np.floating)):
                    # Convert numpy types to Python native types
                    return int(val) if isinstance(val, np.integer) else float(val)
                else:
                    return val
            
            # Clean all values in the dataframe
            df_cleaned = df.applymap(clean_value)
            
            # Convert to dictionary
            data = df_cleaned.to_dict(orient='records')
            
            # Also call MCP tool to get the formatted message
            try:
                result = run_async(import_excel(filepath))
                if result.startswith("Error:"):
                    # If MCP tool fails but pandas succeeded, use pandas result
                    result = f"Successfully imported {len(data)} rows from '{filename}'"
            except Exception:
                # If MCP tool call fails, just use pandas result
                result = f"Successfully imported {len(data)} rows from '{filename}'"
            
            return jsonify({
                'success': True,
                'message': result,
                'filename': filename,
                'filepath': filepath,
                'data': data
            })
        except Exception as e:
            return jsonify({'error': f'Error processing file: {str(e)}'}), 500
    
    return jsonify({'error': 'Invalid file type. Only .xlsx and .xls are allowed'}), 400


@app.route('/api/summary', methods=['POST'])
def get_summary():
    data = request.json
    if not data or 'data' not in data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        # Get summary using MCP tool
        result = run_async(describe_result_summary(data['data']))
        return jsonify({
            'success': True,
            'summary': result
        })
    except Exception as e:
        return jsonify({'error': f'Error generating summary: {str(e)}'}), 500


@app.route('/api/suggest-charts', methods=['POST'])
def suggest_charts_api():
    data = request.json
    if not data or 'data' not in data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        # Get column names and types from data
        if not data['data']:
            return jsonify({'error': 'Empty data'}), 400
        
        columns = list(data['data'][0].keys())
        schema = {
            "columns": columns,
            "types": {col: "unknown" for col in columns}
        }
        
        # Suggest charts
        result = run_async(suggest_charts("", json.dumps(schema)))
        return jsonify({
            'success': True,
            'suggestions': result
        })
    except Exception as e:
        return jsonify({'error': f'Error suggesting charts: {str(e)}'}), 500


@app.route('/api/generate-chart', methods=['POST'])
def generate_chart():
    data = request.json
    if not data or 'chart_type' not in data or 'data' not in data:
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        chart_type = data['chart_type']
        chart_data = data['data']
        
        # Generate chart spec
        spec_json = run_async(generate_chart_spec(chart_type, chart_data))
        spec = json.loads(spec_json)
        
        # Add output path
        chart_filename = f"chart_{chart_type}_{len(chart_data)}_{hash(str(spec)) % 10000}.png"
        chart_path = os.path.join(app.config['CHART_FOLDER'], chart_filename)
        spec['output_path'] = chart_path
        spec['title'] = data.get('title', f'{chart_type.title()} Chart')
        if 'xlabel' in data:
            spec['xlabel'] = data['xlabel']
        if 'ylabel' in data:
            spec['ylabel'] = data['ylabel']
        
        # Render chart
        result = run_async(render_chart(chart_type, json.dumps(spec)))
        
        if os.path.exists(chart_path):
            return jsonify({
                'success': True,
                'message': result,
                'chart_url': f'/static/charts/{chart_filename}'
            })
        else:
            return jsonify({'error': 'Chart generation failed'}), 500
            
    except Exception as e:
        return jsonify({'error': f'Error generating chart: {str(e)}'}), 500


@app.route('/static/charts/<filename>')
def serve_chart(filename):
    chart_path = os.path.join(app.config['CHART_FOLDER'], filename)
    if os.path.exists(chart_path):
        return send_file(chart_path, mimetype='image/png')
    return jsonify({'error': 'Chart not found'}), 404


if __name__ == '__main__':
    app.run(debug=True, port=5000)

