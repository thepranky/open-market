// app.jsx — router, theme, tweaks, mount
const { useState: useS, useEffect: useE, useMemo: useM } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light",
  "cardStyle": "bordered",
  "badgeStyle": "soft",
  "exploreLayout": "tiered",
  "graphLayout": "radial"
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [route, setRoute] = useS({ page: 'home' });

  // expose theme setter for the nav toggle
  window.__meridianSetTheme = (v) => setTweak('theme', v);

  // apply theme
  useE(() => {
    document.documentElement.classList.toggle('dark', t.theme === 'dark');
  }, [t.theme]);

  const navigate = (next) => {
    setRoute(next);
    window.scrollTo({ top: 0, behavior: 'auto' });
  };

  const ctx = useM(() => ({ t, navigate, route }), [t, route]);

  let Page;
  switch (route.page) {
    case 'explore': Page = <ExplorePage />; break;
    case 'case': Page = <CasePage />; break;
    case 'graph': Page = <GraphPage />; break;
    case 'system': Page = <SystemPage />; break;
    default: Page = <HomePage />;
  }

  return (
    <UIContext.Provider value={ctx}>
      <div className="min-h-screen bg-canvas text-ink">
        <NavBar />
        <div key={route.page + (route.id || '')}>{Page}</div>

        <TweaksPanel>
          <TweakSection label="Theme" />
          <TweakRadio label="Mode" value={t.theme} options={['light', 'dark']}
            onChange={(v) => setTweak('theme', v)} />

          <TweakSection label="Cards" />
          <TweakRadio label="Case card style" value={t.cardStyle}
            options={['bordered', 'filled', 'divided']}
            onChange={(v) => setTweak('cardStyle', v)} />

          <TweakSection label="Badges & chips" />
          <TweakRadio label="Badge style" value={t.badgeStyle}
            options={['soft', 'solid', 'outline']}
            onChange={(v) => setTweak('badgeStyle', v)} />

          <TweakSection label="Explore layout" />
          <TweakRadio label="Results" value={t.exploreLayout}
            options={['tiered', 'unified', 'compact']}
            onChange={(v) => setTweak('exploreLayout', v)} />

          <TweakSection label="Graph layout" />
          <TweakRadio label="Drill view" value={t.graphLayout}
            options={['radial', 'columns', 'grid']}
            onChange={(v) => setTweak('graphLayout', v)} />
        </TweaksPanel>
      </div>
    </UIContext.Provider>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
