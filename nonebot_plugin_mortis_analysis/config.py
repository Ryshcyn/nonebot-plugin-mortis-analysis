from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing import Optional


class Config(BaseModel):
    model_config = ConfigDict(extra='ignore')
    mortis_analysis_parse_notice: str = Field(default='小睦将为你解析～', max_length=200)
    mortis_analysis_enabled: bool = Field(default=True, validation_alias=AliasChoices('mortis_analysis_enabled', 'mortis_resolver_enabled'))
    mortis_analysis_nickname: str = Field(default='', max_length=40, validation_alias=AliasChoices('mortis_analysis_nickname', 'mortis_resolver_nickname'))
    mortis_analysis_hot_comment_count: int = Field(default=5, ge=0, le=10, validation_alias=AliasChoices('mortis_analysis_hot_comment_count', 'mortis_resolver_hot_comment_count'))
    mortis_analysis_video_max_duration: int = Field(default=480, ge=1, le=86400, validation_alias=AliasChoices('mortis_analysis_video_max_duration', 'mortis_resolver_video_max_duration'))
    mortis_analysis_video_max_size_mb: int = Field(default=80, ge=1, le=100, validation_alias=AliasChoices('mortis_analysis_video_max_size_mb', 'mortis_resolver_video_max_size_mb'))
    mortis_analysis_bili_sessdata: Optional[str] = Field(default=None, validation_alias=AliasChoices('mortis_analysis_bili_sessdata', 'mortis_resolver_bili_sessdata'))
    mortis_analysis_xhs_ck: Optional[str] = Field(default=None, validation_alias=AliasChoices('mortis_analysis_xhs_ck', 'mortis_resolver_xhs_ck'))
    xhs_ck: Optional[str] = ''
    bili_sessdata: Optional[str] = ''
    r_global_nickname: Optional[str] = ''
    global_resolve_controller: Optional[str] = ""
