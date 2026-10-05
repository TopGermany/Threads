import json
from collections import defaultdict
from datetime import datetime
import random
import os
import statistics

# Load JSON
json_path = r'd:\EOS Marketing\Threads_crawls@\Data_json\final_merged.json'
output_path = r'd:\EOS Marketing\Threads_crawls@\Data_json\views_chart.html'

with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Normalize data structure to be a flat list of posts
if isinstance(data, dict):
    posts_list = []
    for account_key, account_info in data.items():
        acc = account_info.get('account', account_key)
        for post in account_info.get('posts', []):
            post['account'] = acc
            posts_list.append(post)
    data = posts_list

# Aggregate data: account -> date -> list of views
aggregated = defaultdict(lambda: defaultdict(list))
dates = set()

for item in data:
    account_url = item.get('account', '')
    account = account_url.split('/')[-1] if account_url else 'Unknown'
    
    posted_at = item.get('posted_at')
    views = item.get('views')
    
    if views is None:
        views = 0
        
    if not posted_at:
        continue
        
    try:
        # Parse date, assuming ISO format
        dt = datetime.fromisoformat(posted_at)
        date_str = dt.strftime('%Y-%m-%d')
        dates.add(date_str)
        aggregated[account][date_str].append(views)
    except Exception as e:
        print(f"Error parsing date {posted_at}: {e}")

sorted_dates = sorted(list(dates))

# Prepare Chart.js datasets
datasets = []

# Predefined colors for better contrast
colors = [
    '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1', '#000075', '#808080', '#ffffff', '#000000'
]

color_idx = 0
for account, date_counts in aggregated.items():
    color = colors[color_idx % len(colors)]
    color_idx += 1
    
    dataset = {
        'label': account,
        'data': [statistics.median(date_counts[date]) if date in date_counts and date_counts[date] else None for date in sorted_dates],
        'borderColor': color,
        'backgroundColor': color,
        'fill': False,
        'tension': 0.3,
        'spanGaps': True,
        'pointRadius': 4,
        'pointHoverRadius': 6
    }
    datasets.append(dataset)

chart_data = {
    'labels': sorted_dates,
    'datasets': datasets
}

html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Threads Views Chart</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-color: #f8fafc;
        }}
        body {{ 
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
            padding: 2rem; 
            background-color: var(--bg-color); 
            color: var(--text-color);
            margin: 0;
            min-height: 100vh;
        }}
        .header {{
            text-align: center;
            margin-bottom: 2rem;
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5rem;
            background: linear-gradient(to right, #3b82f6, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .chart-container {{ 
            width: 100%; 
            max-width: 1400px; 
            margin: 0 auto; 
            background: var(--card-bg); 
            padding: 2rem; 
            border-radius: 16px; 
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5), 0 4px 6px -2px rgba(0, 0, 0, 0.3); 
            border: 1px solid #334155;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Threads Page Views Comparison</h1>
        <p>Daily median views comparison across multiple pages</p>
    </div>
    <div class="chart-container">
        <canvas id="viewsChart"></canvas>
    </div>
    <script>
        const ctx = document.getElementById('viewsChart').getContext('2d');
        const data = {json.dumps(chart_data)};
        
        // Chart.js default font color
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.font.family = "'Inter', sans-serif";
        
        new Chart(ctx, {{
            type: 'line',
            data: data,
            options: {{
                responsive: true,
                interaction: {{
                    mode: 'index',
                    intersect: false,
                }},
                plugins: {{
                    legend: {{
                        position: 'bottom',
                        labels: {{
                            padding: 20,
                            usePointStyle: true,
                            pointStyle: 'circle'
                        }}
                    }},
                    tooltip: {{
                        backgroundColor: 'rgba(15, 23, 42, 0.9)',
                        titleColor: '#f8fafc',
                        bodyColor: '#cbd5e1',
                        borderColor: '#334155',
                        borderWidth: 1,
                        padding: 12,
                        boxPadding: 6
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        grid: {{
                            color: '#334155',
                            drawBorder: false,
                        }},
                        ticks: {{
                            maxTicksLimit: 30,
                            padding: 10
                        }},
                        title: {{ 
                            display: true, 
                            text: 'Median Views',
                            color: '#94a3b8'
                        }}
                    }},
                    x: {{
                        grid: {{
                            color: '#334155',
                            drawBorder: false,
                        }},
                        title: {{ 
                            display: true, 
                            text: 'Date',
                            color: '#94a3b8'
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""

with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"Chart successfully generated at: {output_path}")
