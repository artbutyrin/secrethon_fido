import { useRef, useLayoutEffect, useState } from 'react';
import {
  motion,
  useScroll,
  useSpring,
  useTransform,
  useMotionValue,
  useVelocity,
  useAnimationFrame,
} from 'motion/react';
import './ScrollVelocity.css';

function useElementHeight(ref) {
  const [height, setHeight] = useState(0);

  useLayoutEffect(() => {
    function updateHeight() {
      if (ref.current) setHeight(ref.current.offsetHeight);
    }
    updateHeight();
    window.addEventListener('resize', updateHeight);
    return () => window.removeEventListener('resize', updateHeight);
  }, [ref]);

  return height;
}

function wrap(min, max, v) {
  const range = max - min;
  const mod = (((v - min) % range) + range) % range;
  return mod + min;
}

function VelocityText({
  children,
  baseVelocity = 100,
  scrollContainerRef,
  className = '',
  damping,
  stiffness,
  numCopies,
  velocityMapping,
  parallaxClassName,
  scrollerClassName,
  parallaxStyle,
  scrollerStyle,
}) {
  const baseY = useMotionValue(0);
  const scrollOptions = scrollContainerRef ? { container: scrollContainerRef } : {};
  const { scrollY } = useScroll(scrollOptions);
  const scrollVelocity = useVelocity(scrollY);
  const smoothVelocity = useSpring(scrollVelocity, {
    damping: damping ?? 50,
    stiffness: stiffness ?? 400,
  });
  const velocityFactor = useTransform(
    smoothVelocity,
    velocityMapping?.input || [0, 1000],
    velocityMapping?.output || [0, 5],
    { clamp: false },
  );

  const copyRef = useRef(null);
  const copyHeight = useElementHeight(copyRef);
  const directionFactor = useRef(1);

  const y = useTransform(baseY, (v) => {
    if (copyHeight === 0) return '0px';
    return `${wrap(-copyHeight, 0, v)}px`;
  });

  useAnimationFrame((_t, delta) => {
    let moveBy = directionFactor.current * baseVelocity * (delta / 1000);

    if (velocityFactor.get() < 0) directionFactor.current = -1;
    else if (velocityFactor.get() > 0) directionFactor.current = 1;

    moveBy += directionFactor.current * moveBy * velocityFactor.get();
    baseY.set(baseY.get() + moveBy);
  });

  const spans = [];
  for (let i = 0; i < numCopies; i += 1) {
    spans.push(
      <span className={className} key={i} ref={i === 0 ? copyRef : null}>
        {children}
      </span>,
    );
  }

  return (
    <div className={parallaxClassName} style={parallaxStyle}>
      <motion.div className={`${scrollerClassName} scroller--y`} style={{ y, ...scrollerStyle }}>
        {spans}
      </motion.div>
    </div>
  );
}

export const ScrollVelocity = ({
  scrollContainerRef,
  texts = [],
  velocity = 100,
  className = '',
  damping = 50,
  stiffness = 400,
  numCopies = 6,
  velocityMapping = { input: [0, 1000], output: [0, 5] },
  parallaxClassName = 'parallax',
  scrollerClassName = 'scroller',
  parallaxStyle,
  scrollerStyle,
}) => (
  <section>
    {texts.map((text, index) => (
      <VelocityText
        key={index}
        className={className}
        baseVelocity={index % 2 === 0 ? -velocity : velocity}
        scrollContainerRef={scrollContainerRef}
        damping={damping}
        stiffness={stiffness}
        numCopies={numCopies}
        velocityMapping={velocityMapping}
        parallaxClassName={parallaxClassName}
        scrollerClassName={scrollerClassName}
        parallaxStyle={parallaxStyle}
        scrollerStyle={scrollerStyle}
      >
        {text}
      </VelocityText>
    ))}
  </section>
);

export default ScrollVelocity;
