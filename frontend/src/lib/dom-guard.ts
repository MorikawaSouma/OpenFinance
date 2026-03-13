"use client";

declare global {
  interface Window {
    __OF_DOM_GUARD_INSTALLED__?: boolean;
  }
}

function isNotFoundDomError(error: unknown) {
  return error instanceof DOMException && error.name === "NotFoundError";
}

// Guard against third-party DOM mutations (for example, browser translation plugins)
// that can desync the real DOM from React's virtual DOM bookkeeping.
export function installDomMutationGuard() {
  if (typeof window === "undefined") return;
  if (window.__OF_DOM_GUARD_INSTALLED__) return;
  window.__OF_DOM_GUARD_INSTALLED__ = true;

  const originalRemoveChild = Node.prototype.removeChild;
  const originalInsertBefore = Node.prototype.insertBefore;

  Node.prototype.removeChild = function <T extends Node>(child: T): T {
    if (child && child.parentNode !== this) {
      return child;
    }
    try {
      return originalRemoveChild.call(this, child) as T;
    } catch (error) {
      if (isNotFoundDomError(error)) {
        return child;
      }
      throw error;
    }
  };

  Node.prototype.insertBefore = function <T extends Node>(newNode: T, referenceNode: Node | null): T {
    if (referenceNode && referenceNode.parentNode !== this) {
      return this.appendChild(newNode) as T;
    }
    try {
      return originalInsertBefore.call(this, newNode, referenceNode) as T;
    } catch (error) {
      if (isNotFoundDomError(error)) {
        return this.appendChild(newNode) as T;
      }
      throw error;
    }
  };
}

