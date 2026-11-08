import React from 'react';
import {Composition} from 'remotion';
import {LyricVideo, calculateMetadata, defaultProps} from './LyricVideo';

// Size, frame rate and length come from calculateMetadata (it reads public/LYRICS_TIMING.json),
// so they are not set here.
export const Root: React.FC = () => (
  <Composition
    id="LyricVideo"
    component={LyricVideo}
    defaultProps={defaultProps}
    calculateMetadata={calculateMetadata}
  />
);
