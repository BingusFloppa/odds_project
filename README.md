# Football Value Bet Analyzer

A football betting-analysis project that uses The Odds API's sports data with a bivariate Poisson model to estimate match outcome probabilities, identify potential value bets, and track their results through virtual bets.

The project is designed for research and backtesting purposes. It does not place real-money bets.

---

## Overview

User manually fetches football fixtures and bookmaker odds from The Odds API(https://the-odds-api.com/), models expected goals using a bivariate Poisson distribution, and compares the model's estimated probabilities with the implied probabilities from available market odds.

When the model identifies a potential value bet, the system records a virtual 1 stake in a separate page.

Once the match has finished, the system will retrieve the result and settles the virtual bet as either win or loss.

This makes it possible to evaluate whether the model's identified edges would have been profitable over a larger sample of matches.

This software provides statistical estimates and simulated betting results for educational and research purposes. It does not guarantee profitable betting outcomes and does not place real-money bets.
