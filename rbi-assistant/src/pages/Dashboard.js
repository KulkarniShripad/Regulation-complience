import React, { useState } from 'react';
import Sidebar from '../components/Sidebar';
import ChatPage from './ChatPage';
import UploadPage from './UploadPage';
import VisualizationPage from './VisualizationPage';
import CompliancePage from './CompliancePage';
import './Dashboard.css';

const PAGES = {
  chat:        ChatPage,
  upload:      UploadPage,
  visualize:   VisualizationPage,
  compliance:  CompliancePage,
};

export default function Dashboard() {
  const [activePage, setActivePage] = useState('chat');
  const Page = PAGES[activePage] || ChatPage;

  return (
    <div className="dashboard">
      <Sidebar active={activePage} onNav={setActivePage} />
      <main className="dashboard-main">
        <Page />
      </main>
    </div>
  );
}
