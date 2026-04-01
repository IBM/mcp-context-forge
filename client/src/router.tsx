import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

interface RouterContextType {
  currentPath: string;
  navigate: (path: string) => void;
  isActive: (path: string) => boolean;
  basepath: string;
}

const RouterContext = createContext<RouterContextType | undefined>(undefined);

interface RouterProps {
  children: ReactNode;
  basepath?: string;
}

export function Router({ children, basepath = '' }: RouterProps) {
  const [currentPath, setCurrentPath] = useState(window.location.pathname);

  useEffect(() => {
    const handlePopState = () => {
      setCurrentPath(window.location.pathname);
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigate = (path: string) => {
    const fullPath = basepath + path;
    window.history.pushState({}, '', fullPath);
    setCurrentPath(fullPath);
  };

  const isActive = (path: string) => {
    const fullPath = basepath + path;
    return currentPath === fullPath;
  };

  return (
    <RouterContext.Provider value={{ currentPath, navigate, isActive, basepath }}>
      {children}
    </RouterContext.Provider>
  );
}

export function useRouter(): RouterContextType {
  const context = useContext(RouterContext);
  if (!context) {
    throw new Error('useRouter must be used within a Router');
  }
  return context;
}

interface LinkProps {
  to: string;
  children: ReactNode;
  className?: string;
}

export function Link({ to, children, className }: LinkProps) {
  const { navigate, basepath } = useRouter();

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    navigate(to);
  };

  return (
    <a href={basepath + to} onClick={handleClick} className={className}>
      {children}
    </a>
  );
}

interface RouteProps {
  path: string;
  component: React.ComponentType;
}

export function Route({ path, component: Component }: RouteProps) {
  const { currentPath, basepath } = useRouter();
  const fullPath = basepath + path;
  
  if (currentPath === fullPath) {
    return <Component />;
  }
  return null;
}

interface RoutesProps {
  children: ReactNode;
}

export function Routes({ children }: RoutesProps) {
  return <>{children}</>;
}