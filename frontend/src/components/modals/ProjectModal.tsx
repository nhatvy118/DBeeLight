import { useState } from 'react';
import Modal from './Modal';
import { Icons } from '../../icons';

type ProjectModalProps = {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (name: string, description?: string) => void;
};

export default function ProjectModal({ isOpen, onClose, onCreate }: ProjectModalProps) {
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (projectName.trim()) {
      onCreate(projectName.trim(), projectDescription.trim() || undefined);
      setProjectName('');
      setProjectDescription('');
      onClose();
    }
  };

  return (
    <Modal title="New project" subtitle="Group related chats and data together." icon={Icons.FolderPlus} onClose={onClose} width={480}>
      <form onSubmit={handleSubmit}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <label htmlFor="project-name" className="field-label">Project name</label>
            <input
              id="project-name"
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="e.g. Q2 Revenue Review"
              className="field focusable"
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="project-description" className="field-label">
              Description <span style={{ color: 'var(--text-faint)', fontWeight: 400 }}>(optional)</span>
            </label>
            <textarea
              id="project-description"
              value={projectDescription}
              onChange={(e) => setProjectDescription(e.target.value)}
              placeholder="What is this project about?"
              rows={3}
              className="field focusable"
            />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
          <button type="button" className="btn btn-outline" style={{ flex: '0 0 auto', padding: '12px 20px' }} onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" style={{ flex: 1, padding: '12px 20px' }}>
            <Icons.Plus size={16} /> Create project
          </button>
        </div>
      </form>
    </Modal>
  );
}
