"""Initial schema migration

Revision ID: 001_initial
Revises: 
Create Date: 2026-01-05 08:31:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial database schema."""
    
    # Create videos table
    op.create_table(
        'videos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('source_url', sa.String(), nullable=True),
        sa.Column('thumbnail_path', sa.String(), nullable=True),
        sa.Column('gif_preview_path', sa.String(), nullable=True),
        sa.Column('preview_path', sa.String(), nullable=True),
        sa.Column('duration', sa.Float(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('batch_name', sa.String(), nullable=True),
        sa.Column('tags', sa.String(), nullable=True),
        sa.Column('ai_tags', sa.String(), nullable=True),
        sa.Column('subtitle', sa.Text(), nullable=True),
        sa.Column('sprite_path', sa.String(), nullable=True),
        sa.Column('storage_type', sa.String(), nullable=True),
        sa.Column('is_favorite', sa.Boolean(), nullable=True),
        sa.Column('is_watched', sa.Boolean(), nullable=True),
        sa.Column('resume_time', sa.Float(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('error_msg', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('phash', sa.String(), nullable=True),
        sa.Column('duplicate_of', sa.Integer(), nullable=True),
        sa.Column('last_checked', sa.DateTime(), nullable=True),
        sa.Column('link_status', sa.String(), nullable=True),
        sa.Column('check_count', sa.Integer(), nullable=True),
        sa.Column('download_stats', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for videos table
    op.create_index(op.f('ix_videos_id'), 'videos', ['id'], unique=False)
    op.create_index(op.f('ix_videos_title'), 'videos', ['title'], unique=False)
    op.create_index(op.f('ix_videos_batch_name'), 'videos', ['batch_name'], unique=False)
    op.create_index(op.f('ix_videos_phash'), 'videos', ['phash'], unique=False)
    
    # Create smart_playlists table
    op.create_table(
        'smart_playlists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('rules', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for smart_playlists table
    op.create_index(op.f('ix_smart_playlists_id'), 'smart_playlists', ['id'], unique=False)
    op.create_index(op.f('ix_smart_playlists_name'), 'smart_playlists', ['name'], unique=True)
    
    # Create search_history table
    op.create_table(
        'search_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('results_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for search_history table
    op.create_index(op.f('ix_search_history_id'), 'search_history', ['id'], unique=False)
    op.create_index(op.f('ix_search_history_query'), 'search_history', ['query'], unique=False)


def downgrade() -> None:
    """Drop all tables."""
    op.drop_index(op.f('ix_search_history_query'), table_name='search_history')
    op.drop_index(op.f('ix_search_history_id'), table_name='search_history')
    op.drop_table('search_history')
    
    op.drop_index(op.f('ix_smart_playlists_name'), table_name='smart_playlists')
    op.drop_index(op.f('ix_smart_playlists_id'), table_name='smart_playlists')
    op.drop_table('smart_playlists')
    
    op.drop_index(op.f('ix_videos_phash'), table_name='videos')
    op.drop_index(op.f('ix_videos_batch_name'), table_name='videos')
    op.drop_index(op.f('ix_videos_title'), table_name='videos')
    op.drop_index(op.f('ix_videos_id'), table_name='videos')
    op.drop_table('videos')
