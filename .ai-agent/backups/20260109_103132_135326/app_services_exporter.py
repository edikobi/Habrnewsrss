import json
import datetime
from typing import Dict, Any, List
from pathlib import Path
from sqlalchemy.orm import Session

from app.database import User, UserProgress, ContentItem, get_db_session, SessionLocal

class ProgressExporter:
    """Exports user progress to JSON and Markdown formats."""

    def __init__(self, db_session: Session = None):
        self.db_session = db_session or SessionLocal()

    def export_to_json(self, user_id: int, filepath: str) -> bool:
        """Export user data to JSON."""
        try:
            data = self._generate_resume_data(user_id)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"JSON Export error: {e}")
            return False

    def export_to_markdown(self, user_id: int, filepath: str) -> bool:
        """Export user data to Markdown."""
        try:
            data = self._generate_resume_data(user_id)
            md = f"# Learning Progress: {data['username']}\n"
            md += f"Generated on: {data['export_date']}\n\n"
            
            md += "## Summary Statistics\n"
            md += f"- Total Completed: {data['stats']['total_completed']}\n"
            md += f"- Total Study Time: {data['stats']['total_hours']:.1f} hours\n"
            md += f"- Average Rating: {data['stats']['avg_rating']:.1f}/5\n\n"
            
            md += "## Skills Learned\n"
            for tag, count in data['stats']['top_tags'].items():
                md += f"- **{tag}**: {count} items\n"
            
            md += "\n## Completed Content\n"
            for item in data['completed_items']:
                md += f"### {item['title']}\n"
                md += f"- Platform: {item['platform']}\n"
                md += f"- Date: {item['completed_at']}\n"
                if item['notes']:
                    md += f"- Notes: {item['notes']}\n"
                md += "\n"

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(md)
            return True
        except Exception as e:
            print(f"Markdown Export error: {e}")
            return False

    def _generate_resume_data(self, user_id: int) -> Dict[str, Any]:
        """Gather all user progress data for export."""
        user = self.db_session.query(User).get(user_id)
        progress = self.db_session.query(UserProgress).filter_by(user_id=user_id, completed=True).all()
        
        total_minutes = user.total_study_time()
        
        tag_counts = {}
        completed_list = []
        ratings = []
        
        for p in progress:
            item = p.content
            if p.rating: ratings.append(p.rating)
            for t in item.tags:
                tag_counts[t.name] = tag_counts.get(t.name, 0) + 1
            
            completed_list.append({
                'title': item.title,
                'platform': item.platform,
                'completed_at': p.completed_at.strftime('%Y-%m-%d') if p.completed_at else 'N/A',
                'notes': p.notes
            })

        return {
            'username': user.username,
            'export_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'stats': {
                'total_completed': len(progress),
                'total_hours': total_minutes / 60,
                'avg_rating': sum(ratings) / len(ratings) if ratings else 0,
                'top_tags': dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10])
            },
            'completed_items': completed_list
        }