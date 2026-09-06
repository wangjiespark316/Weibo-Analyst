CREATE TABLE IF NOT EXISTS weibo_comments (
  id           BIGINT UNSIGNED AUTO_INCREMENT COMMENT '自增主键',
  comment_id   VARCHAR(32)  NOT NULL COMMENT '评论ID（唯一，幂等去重）',
  weibo_id     VARCHAR(32)  NOT NULL COMMENT '所属微博ID（关联 weibo_posts.weibo_id）',
  post_id      BIGINT UNSIGNED DEFAULT NULL COMMENT '所属帖子内部ID（关联 weibo_posts.id）',
  user_id      VARCHAR(50)  DEFAULT NULL COMMENT '评论用户ID',
  username     VARCHAR(100) DEFAULT NULL COMMENT '评论用户昵称',
  content      TEXT COMMENT '评论内容（清洗后纯文本）',
  like_count   INT          NOT NULL DEFAULT 0 COMMENT '点赞数',
  created_time DATETIME     DEFAULT NULL COMMENT '评论真实发布时间',
  is_hot       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '热评标记 0否 1是',
  crawl_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '爬取时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_comment_id (comment_id),
  KEY idx_weibo_id (weibo_id),
  KEY idx_post_id (post_id),
  KEY idx_user_id (user_id),
  KEY idx_created_time (created_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='微博评论表（统一，新数据入口）';
