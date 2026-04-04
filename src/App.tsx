import { useNavigationStore } from '@/store/navigationStore';
import { ProjectListScreen } from '@/screens/ProjectListScreen';
import { NewProjectScreen } from '@/screens/NewProjectScreen';
import { WorkspaceLayout } from '@/components/WorkspaceLayout';
import { DesktopInvoiceScreen } from '@/screens/DesktopInvoiceScreen';
import { BattleshipLabScreen } from '@/screens/BattleshipLabScreen';
import { WallBattleshipControlsWindow } from '@/components/WallBattleshipControlsWindow';
import { useEffect } from 'react';

export default function App() {
  useEffect(() => {
    const guard = (e: DragEvent) => {
      // Prevent browser default "open file in tab" behavior.
      e.preventDefault();
    };
    window.addEventListener('dragover', guard);
    window.addEventListener('drop', guard);
    return () => {
      window.removeEventListener('dragover', guard);
      window.removeEventListener('drop', guard);
    };
  }, []);

  const appMode =
    new URLSearchParams(window.location.search).get('appMode') ||
    (window.desktopApi ? 'invoice' : 'web');

  if (window.desktopApi && appMode === 'invoice') {
    return <DesktopInvoiceScreen />;
  }

  if (appMode === 'battleship') {
    return (
      <div className="h-full min-h-screen">
        <BattleshipLabScreen />
      </div>
    );
  }

  if (appMode === 'battleship-controls') {
    return <WallBattleshipControlsWindow />;
  }

  const screen = useNavigationStore((s) => s.screen);

  return (
    <div className="h-full min-h-screen">
      {screen === 'projects' && <ProjectListScreen />}
      {screen === 'new-project' && <NewProjectScreen />}
      {screen === 'workspace' && <WorkspaceLayout />}
      {screen === 'battleship-lab' && <BattleshipLabScreen />}
    </div>
  );
}
