CREATE DATABASE IF NOT EXISTS `laliga_predictor` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `laliga_predictor`;

CREATE TABLE IF NOT EXISTS `matches` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `division` VARCHAR(50) DEFAULT 'SP1',
  `season` VARCHAR(10) DEFAULT '2627',
  `match_date` DATETIME NULL,
  `home_team` VARCHAR(100) NOT NULL,
  `away_team` VARCHAR(100) NOT NULL,
  `home_norm` VARCHAR(100) NOT NULL,
  `away_norm` VARCHAR(100) NOT NULL,
  `ft_home` INT NOT NULL,
  `ft_away` INT NOT NULL,
  `home_shots` FLOAT NULL,
  `away_shots` FLOAT NULL,
  `home_target` FLOAT NULL,
  `away_target` FLOAT NULL,
  `home_corners` FLOAT NULL,
  `away_corners` FLOAT NULL,
  `home_yellow` FLOAT NULL,
  `away_yellow` FLOAT NULL,
  `home_red` FLOAT NULL,
  `away_red` FLOAT NULL,
  `home_elo` FLOAT NULL,
  `away_elo` FLOAT NULL,
  INDEX `idx_season` (`season`),
  INDEX `idx_home_norm` (`home_norm`),
  INDEX `idx_away_norm` (`away_norm`),
  INDEX `idx_match_date` (`match_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `odds` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `match_date` DATETIME NULL,
  `home_norm` VARCHAR(100) NOT NULL,
  `away_norm` VARCHAR(100) NOT NULL,
  `avg_home` FLOAT NULL,
  `avg_draw` FLOAT NULL,
  `avg_away` FLOAT NULL,
  INDEX `idx_odds_teams` (`home_norm`, `away_norm`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
