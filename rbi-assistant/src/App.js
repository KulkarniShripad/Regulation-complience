import React, { useState } from 'react';
import LandingPage from './pages/LandingPage';
import Dashboard from './pages/Dashboard';

export default function App() {
  const [started, setStarted] = useState(false);

  if (!started) return <LandingPage onStart={() => setStarted(true)} />;
  return <Dashboard />;
}
