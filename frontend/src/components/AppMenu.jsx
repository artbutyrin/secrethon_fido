import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import StaggeredMenu from './StaggeredMenu';

const MENU_ITEMS = [
  { label: 'Home', ariaLabel: 'Go to home — hero', link: '/' },
  { label: 'Invest', ariaLabel: 'Go to underwrite prompt', link: '/#underwrite' },
  { label: 'About', ariaLabel: 'Go to about section', link: '/#next' },
  { label: 'History', ariaLabel: 'Open saved memos', link: '/history' },
];

const LIGHT = '#120f17';
const DARK = '#f4f1ea';

/** Fixed StaggeredMenu on every route — palette matches hero SideRays / dither. */
export default function AppMenu() {
  const { pathname, hash } = useLocation();
  // 'dark' = white menu (hero / about fibers), 'light' = black menu (invest paper)
  const [surface, setSurface] = useState(pathname === '/' ? 'dark' : 'light');

  useEffect(() => {
    if (pathname !== '/') {
      setSurface('light');
      return undefined;
    }

    const sync = () => {
      const underwrite = document.getElementById('underwrite');
      const next = document.getElementById('next');
      const mid = window.innerHeight * 0.45;

      if (next && next.getBoundingClientRect().top < mid) {
        setSurface('dark');
        return;
      }
      if (underwrite && underwrite.getBoundingClientRect().top < mid) {
        setSurface('light');
        return;
      }
      setSurface('dark');
    };

    sync();
    window.addEventListener('scroll', sync, { passive: true });
    window.addEventListener('resize', sync);
    return () => {
      window.removeEventListener('scroll', sync);
      window.removeEventListener('resize', sync);
    };
  }, [pathname, hash]);

  const menuColor = surface === 'light' ? LIGHT : DARK;

  return (
    <StaggeredMenu
      position="right"
      items={MENU_ITEMS}
      socialItems={[]}
      displaySocials={false}
      displayItemNumbering
      isFixed
      menuButtonColor={menuColor}
      openMenuButtonColor={LIGHT}
      changeMenuColorOnOpen
      colors={['#008a48', '#96c8ff']}
      accentColor="#008a48"
    />
  );
}
