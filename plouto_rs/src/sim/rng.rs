use rand::Rng;
use rand_chacha::ChaCha8Rng;
use rand::SeedableRng;
use sha2::{Digest, Sha256};

#[derive(Debug, Clone)]
pub struct SimRng {
    inner: ChaCha8Rng,
    seed: u64,
    draws: u64,
}

impl SimRng {
    pub fn new(seed: u64) -> Self {
        Self {
            inner: ChaCha8Rng::seed_from_u64(seed),
            seed,
            draws: 0,
        }
    }

    #[inline]
    pub fn seed(&self) -> u64 {
        self.seed
    }

    #[inline]
    pub fn f32(&mut self) -> f32 {
        self.draws += 1;
        self.inner.gen::<f32>()
    }

    #[inline]
    pub fn f64(&mut self) -> f64 {
        self.draws += 1;
        self.inner.gen::<f64>()
    }

    #[inline]
    pub fn range_f32(&mut self, lo: f32, hi: f32) -> f32 {
        self.draws += 1;
        if hi <= lo {
            return lo;
        }
        lo + self.inner.gen::<f32>() * (hi - lo)
    }

    #[inline]
    pub fn range_i32(&mut self, lo: i32, hi_inclusive: i32) -> i32 {
        self.draws += 1;
        if hi_inclusive <= lo {
            return lo;
        }
        self.inner.gen_range(lo..=hi_inclusive)
    }

    #[inline]
    pub fn index(&mut self, len: usize) -> usize {
        self.draws += 1;
        if len <= 1 {
            return 0;
        }
        self.inner.gen_range(0..len)
    }

    pub fn choose<'a, T>(&mut self, items: &'a [T]) -> Option<&'a T> {
        if items.is_empty() {
            return None;
        }
        let idx = self.index(items.len());
        Some(&items[idx])
    }

    pub fn weighted_index(&mut self, weights: &[f32]) -> usize {
        if weights.is_empty() {
            return 0;
        }
        let total: f32 = weights.iter().map(|&w| w.max(0.0)).sum();
        if total <= 0.0 {
            return 0;
        }
        let mut target = self.f32() * total;
        for (i, &w) in weights.iter().enumerate() {
            let ww = w.max(0.0);
            if target < ww {
                return i;
            }
            target -= ww;
        }
        weights.len() - 1
    }

    pub fn shuffle<T>(&mut self, slice: &mut [T]) {
        self.draws += 1;
        use rand::seq::SliceRandom;
        slice.shuffle(&mut self.inner);
    }

    /// Deterministic hash representing RNG state + position in stream.
    pub fn state_fingerprint(&self) -> String {
        let mut h = Sha256::new();
        h.update(self.seed.to_le_bytes());
        h.update(self.draws.to_le_bytes());
        h.update(self.inner.get_word_pos().to_le_bytes());
        h.update(self.inner.get_seed());
        format!("{:x}", h.finalize())
    }
}
