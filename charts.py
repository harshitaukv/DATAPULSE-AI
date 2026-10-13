"""Small Plotly builders shared by several pages."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from components.theme import BAD, INK, LINE, MUTED, OK, QUALITY, VALIDATE, WARN, register_plotly, tint


def donut(labels: list[str], values: list[float], colors: list[str], title: str, center: str = "",
          sub: str = "", height: int = 290) -> go.Figure:
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=.68, sort=False, direction="clockwise",
                           marker=dict(colors=colors, line=dict(color="#FFFFFF", width=3)),
                           textinfo="none", hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"))
    fig.update_layout(title=title, height=height, showlegend=True,
                      legend=dict(orientation="v", x=1.0, xanchor="left", y=.5, yanchor="middle"),
                      margin=dict(l=8, r=8, t=44, b=8),
                      annotations=[dict(text=f"<b style='font-size:26px'>{center}</b><br>"
                                         f"<span style='color:{MUTED};font-size:12px'>{sub}</span>",
                                         x=.5, y=.5, xref="paper", yref="paper", showarrow=False,
                                         font=dict(color=INK))])
    fig.update_traces(domain=dict(x=[0, .72]))
    fig.layout.annotations[0].x = .36
    return fig


def gauge(value: float | None, title: str, height: int = 250) -> go.Figure:
    v = value or 0
    color = OK if v >= 95 else (QUALITY if v >= 85 else (WARN if v >= 70 else BAD))
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=v, number=dict(suffix="", font=dict(size=40, color=INK), valueformat=".1f"),
        gauge=dict(axis=dict(range=[0, 100], tickwidth=0, tickcolor=LINE, tickfont=dict(color=MUTED, size=10)),
                   bar=dict(color=color, thickness=.32), bgcolor="#F1F2FA", borderwidth=0,
                   steps=[dict(range=[0, 70], color=tint(BAD, .1)), dict(range=[70, 85], color=tint(WARN, .1)),
                          dict(range=[85, 95], color=tint(QUALITY, .12)), dict(range=[95, 100], color=tint(OK, .14))],
                   threshold=dict(line=dict(color=VALIDATE, width=3), thickness=.8, value=v))))
    fig.update_layout(title=title, height=height, margin=dict(l=24, r=24, t=48, b=4))
    return fig


def show(fig: go.Figure) -> None:
    register_plotly()
    t = pio.templates["datapulse"].layout
    fig.update_layout(template="datapulse", paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                      font=t.font, title_font=t.title.font, colorway=t.colorway, hoverlabel=t.hoverlabel)
    fig.update_xaxes(showgrid=False, linecolor=LINE, tickcolor=LINE, zeroline=False, automargin=True)
    fig.update_yaxes(gridcolor="#ECEEF7", zeroline=False, automargin=True)
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})
