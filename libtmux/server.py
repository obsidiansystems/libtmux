"""Pythonization of the :term:`tmux(1)` server.

libtmux.server
~~~~~~~~~~~~~~

"""
import logging
import os
import typing as t

from libtmux.common import tmux_cmd
from libtmux.session import Session

from . import exc, formats
from .common import (
    EnvironmentMixin,
    PaneDict,
    SessionDict,
    TmuxRelationalObject,
    WindowDict,
    has_gte_version,
    session_check_name,
)

logger = logging.getLogger(__name__)


class Server(TmuxRelationalObject["Session", "SessionDict"], EnvironmentMixin):

    """
    The :term:`tmux(1)` :term:`Server` [server_manual]_.

    - :attr:`Server._sessions` [:class:`Session`, ...]

      - :attr:`Session._windows` [:class:`Window`, ...]

        - :attr:`Window._panes` [:class:`Pane`, ...]

          - :class:`Pane`

    When instantiated stores information on live, running tmux server.

    Parameters
    ----------
    socket_name : str, optional
    socket_path : str, optional
    config_file : str, optional
    colors : str, optional

    Examples
    --------
    >>> server
    <libtmux.server.Server object at ...>

    >>> server.sessions
    [Session($1 ...)]

    >>> server.sessions[0].windows
    [Window(@1 ...:..., Session($1 ...)]

    >>> server.sessions[0].attached_window
    Window(@1 ...:..., Session($1 ...)

    >>> server.sessions[0].attached_pane
    Pane(%1 Window(@1 ...:..., Session($1 ...)))

    References
    ----------
    .. [server_manual] CLIENTS AND SESSIONS. openbsd manpage for TMUX(1)
           "The tmux server manages clients, sessions, windows and panes.
           Clients are attached to sessions to interact with them, either when
           they are created with the new-session command, or later with the
           attach-session command. Each session has one or more windows linked
           into it. Windows may be linked to multiple sessions and are made up
           of one or more panes, each of which contains a pseudo terminal."

       https://man.openbsd.org/tmux.1#CLIENTS_AND_SESSIONS.
       Accessed April 1st, 2018.
    """

    socket_name = None
    """Passthrough to ``[-L socket-name]``"""
    socket_path = None
    """Passthrough to ``[-S socket-path]``"""
    config_file = None
    """Passthrough to ``[-f file]``"""
    colors = None
    """``-2`` or ``-8``"""
    child_id_attribute = "session_id"
    """Unique child ID used by :class:`~libtmux.common.TmuxRelationalObject`"""
    formatter_prefix = "server_"
    """Namespace used for :class:`~libtmux.common.TmuxMappingObject`"""

    def __init__(
        self,
        socket_name: t.Optional[str] = None,
        socket_path: t.Optional[str] = None,
        config_file: t.Optional[str] = None,
        colors: t.Optional[int] = None,
        **kwargs: t.Any,
    ) -> None:
        EnvironmentMixin.__init__(self, "-g")
        self._windows: t.List[WindowDict] = []
        self._panes: t.List[PaneDict] = []

        if socket_name:
            self.socket_name = socket_name

        if socket_path:
            self.socket_path = socket_path

        if config_file:
            self.config_file = config_file

        if colors:
            self.colors = colors

    def cmd(self, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        """
        Execute tmux command and return output.

        Returns
        -------
        :class:`common.tmux_cmd`

        Notes
        -----
        .. versionchanged:: 0.8

            Renamed from ``.tmux`` to ``.cmd``.
        """

        cmd_args: t.List[t.Union[str, int]] = list(args)
        if self.socket_name:
            cmd_args.insert(0, f"-L{self.socket_name}")
        if self.socket_path:
            cmd_args.insert(0, f"-S{self.socket_path}")
        if self.config_file:
            cmd_args.insert(0, f"-f{self.config_file}")
        if self.colors:
            if self.colors == 256:
                cmd_args.insert(0, "-2")
            elif self.colors == 88:
                cmd_args.insert(0, "-8")
            else:
                raise ValueError("Server.colors must equal 88 or 256")

        return tmux_cmd(*cmd_args, **kwargs)

    def _list_sessions(self) -> t.List[SessionDict]:
        """
        Return list of sessions in :py:obj:`dict` form.

        Retrieved from ``$ tmux(1) list-sessions`` stdout.

        The :py:obj:`list` is derived from ``stdout`` in
        :class:`common.tmux_cmd` which wraps :py:class:`subprocess.Popen`.

        Returns
        -------
        list of dict
        """

        sformats = formats.SESSION_FORMATS
        tmux_formats = ["#{%s}" % f for f in sformats]

        tmux_args = ("-F%s" % formats.FORMAT_SEPARATOR.join(tmux_formats),)  # output

        list_sessions_cmd = self.cmd("list-sessions", *tmux_args)

        if list_sessions_cmd.stderr:
            raise exc.LibTmuxException(list_sessions_cmd.stderr)

        sformats = formats.SESSION_FORMATS
        tmux_formats = ["#{%s}" % format for format in sformats]
        sessions_output = list_sessions_cmd.stdout

        # combine format keys with values returned from ``tmux list-sessions``
        sessions_formatters = [
            dict(zip(sformats, session.split(formats.FORMAT_SEPARATOR)))
            for session in sessions_output
        ]

        # clear up empty dict
        sessions_formatters_filtered = [
            {k: v for k, v in session.items() if v} for session in sessions_formatters
        ]

        return sessions_formatters_filtered

    @property
    def _sessions(self) -> t.List[SessionDict]:
        """Property / alias to return :meth:`~._list_sessions`."""

        return self._list_sessions()

    def list_sessions(self) -> t.List[Session]:
        """
        Return list of :class:`Session` from the ``tmux(1)`` session.

        Returns
        -------
        list of :class:`Session`
        """
        return [Session(server=self, **s) for s in self._sessions]

    @property
    def sessions(self) -> t.List[Session]:
        """Property / alias to return :meth:`~.list_sessions`."""
        return self.list_sessions()

    #: Alias :attr:`sessions` for :class:`~libtmux.common.TmuxRelationalObject`
    children = sessions  # type: ignore

    def _list_windows(self) -> t.List[WindowDict]:
        """
        Return list of windows in :py:obj:`dict` form.

        Retrieved from ``$ tmux(1) list-windows`` stdout.

        The :py:obj:`list` is derived from ``stdout`` in
        :class:`common.tmux_cmd` which wraps :py:class:`subprocess.Popen`.

        Returns
        -------
        list of dict
        """

        wformats = ["session_name", "session_id"] + formats.WINDOW_FORMATS
        tmux_formats = ["#{%s}" % format for format in wformats]

        proc = self.cmd(
            "list-windows",  # ``tmux list-windows``
            "-a",
            "-F%s" % formats.FORMAT_SEPARATOR.join(tmux_formats),  # output
        )

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        window_output = proc.stdout

        wformats = ["session_name", "session_id"] + formats.WINDOW_FORMATS

        # combine format keys with values returned from ``tmux list-windows``
        window_formatters = [
            dict(zip(wformats, window.split(formats.FORMAT_SEPARATOR)))
            for window in window_output
        ]

        # clear up empty dict
        window_formatters_filtered = [
            {k: v for k, v in window.items() if v} for window in window_formatters
        ]

        # tmux < 1.8 doesn't have window_id, use window_name
        for w in window_formatters_filtered:
            if "window_id" not in w:
                w["window_id"] = w["window_name"]

        if self._windows:
            self._windows[:] = []

        self._windows.extend(window_formatters_filtered)

        return self._windows

    def _update_windows(self) -> "Server":
        """
        Update internal window data and return ``self`` for chainability.

        Returns
        -------
        :class:`Server`
        """
        self._list_windows()
        return self

    def _list_panes(self) -> t.List[PaneDict]:
        """
        Return list of panes in :py:obj:`dict` form.

        Retrieved from ``$ tmux(1) list-panes`` stdout.

        The :py:obj:`list` is derived from ``stdout`` in
        :class:`util.tmux_cmd` which wraps :py:class:`subprocess.Popen`.

        Returns
        -------
        list
        """

        pformats = [
            "session_name",
            "session_id",
            "window_index",
            "window_id",
            "window_name",
        ] + formats.PANE_FORMATS
        tmux_formats = [("#{%%s}%s" % formats.FORMAT_SEPARATOR) % f for f in pformats]

        proc = self.cmd("list-panes", "-a", "-F%s" % "".join(tmux_formats))  # output

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        pane_output = proc.stdout

        pformats = [
            "session_name",
            "session_id",
            "window_index",
            "window_id",
            "window_name",
        ] + formats.PANE_FORMATS

        # combine format keys with values returned from ``tmux list-panes``
        pane_formatters = [
            dict(zip(pformats, formatter.split(formats.FORMAT_SEPARATOR)))
            for formatter in pane_output
        ]

        # Filter empty values
        pane_formatters_filtered = [
            {
                k: v for k, v in formatter.items() if v or k == "pane_current_path"
            }  # preserve pane_current_path, in case it entered a new process
            # where we may not get a cwd from.
            for formatter in pane_formatters
        ]

        if self._panes:
            self._panes[:] = []

        self._panes.extend(pane_formatters_filtered)

        return self._panes

    def _update_panes(self) -> "Server":
        """
        Update internal pane data and return ``self`` for chainability.

        Returns
        -------
        :class:`Server`
        """
        self._list_panes()
        return self

    @property
    def attached_sessions(self) -> t.Optional[t.List[Session]]:
        """
        Return active :class:`Session` objects.

        Returns
        -------
        list of :class:`Session`
        """

        sessions = self._sessions
        attached_sessions = list()

        for session in sessions:
            attached = session.get("session_attached")
            # for now session_active is a unicode
            if attached != "0":
                logger.debug("session %s attached", session.get("name"))
                attached_sessions.append(session)
            else:
                continue

        return [Session(server=self, **s) for s in attached_sessions] or None

    def has_session(self, target_session: str, exact: bool = True) -> bool:
        """
        Return True if session exists. ``$ tmux has-session``.

        Parameters
        ----------
        target_session : str
            session name
        exact : bool
            match the session name exactly. tmux uses fnmatch by default.
            Internally prepends ``=`` to the session in ``$ tmux has-session``.
            tmux 2.1 and up only.

        Raises
        ------
        :exc:`exc.BadSessionName`

        Returns
        -------
        bool
        """
        session_check_name(target_session)

        if exact and has_gte_version("2.1"):
            target_session = f"={target_session}"

        proc = self.cmd("has-session", "-t%s" % target_session)

        if not proc.returncode:
            return True

        return False

    def kill_server(self) -> None:
        """``$ tmux kill-server``."""
        self.cmd("kill-server")

    def kill_session(self, target_session: t.Union[str, int]) -> "Server":
        """
        Kill the tmux session with ``$ tmux kill-session``, return ``self``.

        Parameters
        ----------
        target_session : str, optional
            target_session: str. note this accepts ``fnmatch(3)``. 'asdf' will
            kill 'asdfasd'.

        Returns
        -------
        :class:`Server`

        Raises
        ------
        :exc:`exc.BadSessionName`
        """
        proc = self.cmd("kill-session", "-t%s" % target_session)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def switch_client(self, target_session: str) -> None:
        """
        ``$ tmux switch-client``.

        Parameters
        ----------
        target_session : str
            name of the session. fnmatch(3) works.

        Raises
        ------
        :exc:`exc.BadSessionName`
        """
        session_check_name(target_session)

        proc = self.cmd("switch-client", "-t%s" % target_session)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def attach_session(self, target_session: t.Optional[str] = None) -> None:
        """``$ tmux attach-session`` aka alias: ``$ tmux attach``.

        Parameters
        ----------
        target_session : str
            name of the session. fnmatch(3) works.

        Raises
        ------
        :exc:`exc.BadSessionName`
        """
        session_check_name(target_session)

        tmux_args: t.Tuple[str, ...] = tuple()
        if target_session:
            tmux_args += ("-t%s" % target_session,)

        proc = self.cmd("attach-session", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def new_session(
        self,
        session_name: t.Optional[str] = None,
        kill_session: bool = False,
        attach: bool = False,
        start_directory: t.Optional[str] = None,
        window_name: t.Optional[str] = None,
        window_command: t.Optional[str] = None,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> Session:
        """
        Return :class:`Session` from  ``$ tmux new-session``.

        Uses ``-P`` flag to print session info, ``-F`` for return formatting
        returns new Session object.

        ``$ tmux new-session -d`` will create the session in the background
        ``$ tmux new-session -Ad`` will move to the session name if it already
        exists. todo: make an option to handle this.

        Parameters
        ----------
        session_name : str, optional
            ::

                $ tmux new-session -s <session_name>
        attach : bool, optional
            create session in the foreground. ``attach=False`` is equivalent
            to::

                $ tmux new-session -d

        Other Parameters
        ----------------
        kill_session : bool, optional
            Kill current session if ``$ tmux has-session``.
            Useful for testing workspaces.
        start_directory : str, optional
            specifies the working directory in which the
            new session is created.
        window_name : str, optional
            ::

                $ tmux new-session -n <window_name>
        window_command : str
            execute a command on starting the session.  The window will close
            when the command exits. NOTE: When this command exits the window
            will close.  This feature is useful for long-running processes
            where the closing of the window upon completion is desired.

        Returns
        -------
        :class:`Session`

        Raises
        ------
        :exc:`exc.BadSessionName`

        Examples
        --------
        Sessions can be created without a session name (0.14.2+):

        >>> server.new_session()
        Session($2 2)

        Creating them in succession will enumerate IDs (via tmux):

        >>> server.new_session()
        Session($3 3)

        With a `session_name`:

        >>> server.new_session(session_name='my session')
        Session($4 my session)
        """
        if session_name is not None:
            session_check_name(session_name)

            if self.has_session(session_name):
                if kill_session:
                    self.cmd("kill-session", "-t%s" % session_name)
                    logger.info("session %s exists. killed it." % session_name)
                else:
                    raise exc.TmuxSessionExists(
                        "Session named %s exists" % session_name
                    )

        logger.debug("creating session %s" % session_name)

        sformats = formats.SESSION_FORMATS
        tmux_formats = ["#{%s}" % f for f in sformats]

        env = os.environ.get("TMUX")

        if env:
            del os.environ["TMUX"]

        tmux_args: t.Tuple[t.Union[str, int], ...] = (
            "-P",
            "-F%s" % formats.FORMAT_SEPARATOR.join(tmux_formats),  # output
        )

        if session_name is not None:
            tmux_args += (f"-s{session_name}",)

        if not attach:
            tmux_args += ("-d",)

        if start_directory:
            tmux_args += ("-c", start_directory)

        if window_name:
            tmux_args += ("-n", window_name)

        # tmux 2.6 gives unattached sessions a tiny default area
        # no need send in -x/-y if they're in a client already, though
        if has_gte_version("2.6") and "TMUX" not in os.environ:
            tmux_args += ("-x", 800, "-y", 600)

        if window_command:
            tmux_args += (window_command,)

        proc = self.cmd("new-session", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        session_stdout = proc.stdout[0]

        if env:
            os.environ["TMUX"] = env

        # Combine format keys with values returned from ``tmux list-windows``
        session_params = dict(
            zip(sformats, session_stdout.split(formats.FORMAT_SEPARATOR))
        )

        # Filter empty values
        session_params = {k: v for k, v in session_params.items() if v}

        session = Session(server=self, **session_params)

        return session
