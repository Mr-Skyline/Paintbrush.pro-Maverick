import { useNavigationStore } from '@/store/navigationStore';
import { ProjectListScreen } from '@/screens/ProjectListScreen';
import { NewProjectScreen } from '@/screens/NewProjectScreen';
import { WorkspaceLayout } from '@/components/WorkspaceLayout';
import { DesktopInvoiceScreen } from '@/screens/DesktopInvoiceScreen';

export default function App() {
  if (window.desktopApi) {
    return <DesktopInvoiceScreen />;
  }

  const screen = useNavigationStore((s) => s.screen);

  return (
    <div className="h-full min-h-screen">
      {screen === 'projects' && <ProjectListScreen />}
      {screen === 'new-project' && <NewProjectScreen />}
      {screen === 'workspace' && <WorkspaceLayout />}
    </div>
  );
}
