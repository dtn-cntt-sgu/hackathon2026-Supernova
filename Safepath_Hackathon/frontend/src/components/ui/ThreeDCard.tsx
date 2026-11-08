"use client";

import React, {
  createContext,
  useState,
  useContext,
  useRef,
  useEffect,
  useCallback,
} from "react";

const MouseEnterContext = createContext<
  [boolean, React.Dispatch<React.SetStateAction<boolean>>] | undefined
>(undefined);

export interface CardContainerProps {
  children?: React.ReactNode;
  className?: string;
  containerClassName?: string;
  perspective?: number;
  maxTilt?: number;
}

/**
 * 3D Card Container — Ultra-Smooth Architecture
 * - Outer wrapper (wrapperRef): Stationary measurement boundary, ZERO transform applied.
 * - Inner card (cardRef): Dedicated transform element.
 * - Decoupled measurement eliminates the pointer coordinate feedback loop.
 */
export const CardContainer = ({
  children,
  className = "",
  containerClassName = "",
  perspective = 1400,
  maxTilt = 2.5, // Subtle, refined tilt (max 2.5 degrees)
}: CardContainerProps) => {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const [isMouseEntered, setIsMouseEntered] = useState(false);
  const rafId = useRef(0);
  const isTouch = useRef(false);

  useEffect(() => {
    isTouch.current =
      typeof window !== "undefined" &&
      (window.matchMedia("(pointer: coarse)").matches ||
        window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
        window.innerWidth < 1024);
  }, []);

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (isTouch.current || !wrapperRef.current || !cardRef.current) return;

      // Measure ONLY against the stationary wrapper to prevent feedback jitter
      const rect = wrapperRef.current.getBoundingClientRect();
      if (!rect.width || !rect.height) return;

      const normalizedX = (e.clientX - rect.left - rect.width / 2) / (rect.width / 2);
      const normalizedY = (e.clientY - rect.top - rect.height / 2) / (rect.height / 2);

      const rotateY = Math.max(-maxTilt, Math.min(maxTilt, normalizedX * maxTilt));
      const rotateX = Math.max(-maxTilt, Math.min(maxTilt, -normalizedY * maxTilt));

      if (rafId.current) cancelAnimationFrame(rafId.current);
      rafId.current = requestAnimationFrame(() => {
        if (cardRef.current) {
          cardRef.current.style.transform = `perspective(${perspective}px) rotateY(${rotateY.toFixed(2)}deg) rotateX(${rotateX.toFixed(2)}deg)`;
        }
      });
    },
    [maxTilt, perspective]
  );

  const handlePointerEnter = () => {
    if (isTouch.current) return;
    setIsMouseEntered(true);
  };

  const handlePointerLeave = () => {
    if (isTouch.current) return;
    setIsMouseEntered(false);
    if (rafId.current) cancelAnimationFrame(rafId.current);
    if (cardRef.current) {
      cardRef.current.style.transform = `perspective(${perspective}px) rotateY(0deg) rotateX(0deg)`;
    }
  };

  useEffect(() => {
    return () => {
      if (rafId.current) cancelAnimationFrame(rafId.current);
    };
  }, []);

  return (
    <MouseEnterContext.Provider value={[isMouseEntered, setIsMouseEntered]}>
      {/* Outer Stationary Hit Boundary */}
      <div
        ref={wrapperRef}
        onPointerEnter={handlePointerEnter}
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
        className={`relative isolate ${containerClassName}`}
        style={{ perspective: `${perspective}px` }}
      >
        {/* Inner Transforming Content */}
        <div
          ref={cardRef}
          className={`relative w-full h-full transition-transform duration-200 ease-out will-change-transform ${className}`}
          style={{ transformStyle: "preserve-3d" }}
        >
          {children}
        </div>
      </div>
    </MouseEnterContext.Provider>
  );
};

export const CardBody = ({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) => {
  return (
    <div
      className={`w-full h-full [transform-style:preserve-3d] [&>*]:[transform-style:preserve-3d] ${className}`}
    >
      {children}
    </div>
  );
};

export interface CardItemProps extends React.HTMLAttributes<HTMLElement> {
  as?: React.ElementType;
  children: React.ReactNode;
  className?: string;
  translateX?: number | string;
  translateY?: number | string;
  translateZ?: number | string;
  rotateX?: number | string;
  rotateY?: number | string;
  rotateZ?: number | string;
}

export const CardItem = ({
  as: Tag = "div",
  children,
  className = "",
  translateX = 0,
  translateY = 0,
  translateZ = 0,
  rotateX = 0,
  rotateY = 0,
  rotateZ = 0,
  ...rest
}: CardItemProps) => {
  const ref = useRef<HTMLDivElement>(null);
  const [isMouseEntered] = useMouseEnter();

  useEffect(() => {
    if (!ref.current) return;
    if (isMouseEntered) {
      ref.current.style.transform = `translateX(${translateX}px) translateY(${translateY}px) translateZ(${translateZ}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) rotateZ(${rotateZ}deg)`;
    } else {
      ref.current.style.transform = `translateX(0px) translateY(0px) translateZ(0px) rotateX(0deg) rotateY(0deg) rotateZ(0deg)`;
    }
  }, [isMouseEntered, translateX, translateY, translateZ, rotateX, rotateY, rotateZ]);

  return (
    <Tag
      ref={ref}
      className={`transition-transform duration-200 ease-out will-change-transform ${className}`}
      {...rest}
    >
      {children}
    </Tag>
  );
};

export const useMouseEnter = () => {
  const context = useContext(MouseEnterContext);
  if (context === undefined) {
    throw new Error("useMouseEnter must be used within a CardContainer");
  }
  return context;
};
