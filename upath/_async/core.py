"""Core :class:`AsyncUPath` implementation.

``AsyncUPath`` is a thin async I/O layer composed *over* the synchronous
``UPath`` class tree. For every registered protocol we synthesize an async
subclass ``type("Async<Name>", (_AsyncPathMixin, <SyncImpl>), ...)`` so that:

* path algebra, parsing, chaining, flavours and construction come unchanged
  from the synchronous implementation, and
* filesystem I/O comes from :class:`_AsyncPathMixin` as coroutines /
  async iterators.

Instances are created through the :class:`AsyncUPath` factory exactly like
``UPath``::

    p = AsyncUPath("s3://bucket/key", anon=True)
    data = await p.read_bytes()
"""

from __future__ import annotations

import warnings
from pathlib import PurePath
from typing import TYPE_CHECKING
from typing import Any

from upath._async._fs import _AsyncFileWrapper
from upath._async._fs import has_working_open_async
from upath._async._fs import resolve_async_fs
from upath._async._info import AsyncUPathInfo
from upath._async._offload import executor_for
from upath._async._offload import run_in_thread
from upath._protocol import get_upath_protocol
from upath._stat import UPathStatResult
from upath.core import UPath
from upath.registry import _get_implementation_protocols
from upath.registry import get_upath_class
from upath.types import UNSET_DEFAULT

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from collections.abc import Callable

    from fsspec.asyn import AsyncFileSystem

    from upath.types import JoinablePathLike

__all__ = ["AsyncUPath", "get_async_upath_class"]


# --- async subclass synthesis / dispatch ----------------------------------

_async_class_cache: dict[type[UPath], type[AsyncUPath]] = {}


def _async_class_for(sync_cls: type[UPath]) -> type[AsyncUPath]:
    """Return (and cache) the async subclass mixing async I/O over ``sync_cls``."""
    try:
        return _async_class_cache[sync_cls]
    except KeyError:
        pass
    name = f"Async{sync_cls.__name__}"
    # Compose async I/O over the synchronous implementation class so that path
    # algebra / flavour customizations are reused unchanged. We deliberately do
    # NOT inherit from AsyncUPath here: some sync impls (PosixUPath/WindowsUPath)
    # mix stdlib ``pathlib`` and have an instance layout incompatible with the
    # ``pathlib_abc``-based AsyncUPath. Instead we register the generated class
    # as a virtual subclass of AsyncUPath below, so ``isinstance(x, AsyncUPath)``
    # still holds without an instance-layout conflict.
    async_cls = type(
        name,
        (_AsyncPathMixin, sync_cls),
        {
            "__slots__": ("_async_fs_cached",),
            "_sync_class": sync_cls,
            "__module__": __name__,
            "__qualname__": name,
        },
    )
    AsyncUPath.register(async_cls)  # type: ignore[arg-type]
    # Preserve backend-specific I/O customizations: where the sync class
    # overrides one of these methods with custom logic -- e.g. DataPath.glob
    # returning [], S3Path.mkdir's exist_ok semantics, or the read-only backends
    # (http/data/github/hf/zip/tar) whose writes raise UnsupportedOperation --
    # the generic async implementation from _AsyncPathMixin would lose that
    # behavior. For those methods we offload the sync override to a thread so it
    # reproduces the exact semantics. Backends that don't customize a method keep
    # the generic (natively-async where possible) implementation.
    _attach_offloaded_overrides(async_cls, sync_cls)
    # Expose the generated class as a module global so it is picklable by
    # qualified name (``upath._async.core.Async<Name>``).
    globals()[name] = async_cls
    _async_class_cache[sync_cls] = async_cls  # type: ignore[assignment]
    return async_cls  # type: ignore[return-value]


# methods whose sync customization must be preserved (offloaded to a thread)
_OFFLOAD_SCALAR = (
    "stat",
    "exists",
    "is_dir",
    "is_file",
    "mkdir",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
)
_OFFLOAD_GENERATOR = ("iterdir", "glob", "rglob", "walk")


def _attach_offloaded_overrides(async_cls: type, sync_cls: type[UPath]) -> None:
    def _customizes(method: str) -> bool:
        # stdlib-pathlib-backed local classes (PosixUPath/WindowsUPath) work
        # fine through the generic async layer, so never offload for them.
        if issubclass(sync_cls, PurePath):
            return False
        return getattr(sync_cls, method, None) is not getattr(UPath, method, None)

    for method in _OFFLOAD_SCALAR:
        if _customizes(method):
            setattr(async_cls, method, _make_offloaded_scalar(method))
    for method in _OFFLOAD_GENERATOR:
        if _customizes(method):
            setattr(async_cls, method, _make_offloaded_generator(method))


def _make_offloaded_scalar(method: str) -> Any:
    async def _offloaded(self: Any, *args: Any, **kwargs: Any) -> Any:
        sync_self = self._sync_view()
        return await run_in_thread(
            getattr(sync_self, method),
            *args,
            executor=executor_for(self.fs),
            **kwargs,
        )

    _offloaded.__name__ = method
    return _offloaded


def _make_offloaded_generator(method: str) -> Any:
    async def _offloaded(self: Any, *args: Any, **kwargs: Any) -> Any:
        sync_self = self._sync_view()
        items = await run_in_thread(
            lambda: list(getattr(sync_self, method)(*args, **kwargs)),
            executor=executor_for(self.fs),
        )
        for item in items:
            if method == "walk":
                dirpath, dirnames, filenames = item
                yield self.with_segments(str(dirpath)), dirnames, filenames
            else:
                yield self.with_segments(str(item))

    _offloaded.__name__ = method
    return _offloaded


def get_async_upath_class(
    protocol: str,
    *,
    fallback: bool = True,
) -> type[AsyncUPath] | None:
    """Return the :class:`AsyncUPath` subclass for ``protocol``.

    Reuses the synchronous registry (:func:`upath.registry.get_upath_class`)
    to resolve the implementation class, then wraps it with the async I/O
    mixin. Returns ``None`` for unsupported protocols when ``fallback`` allows.
    """
    sync_cls = get_upath_class(protocol, fallback=fallback)
    if sync_cls is None:
        return None
    return _async_class_for(sync_cls)


# reused across the follow_symlinks warnings on stat/exists/is_dir/is_file
_IGNORED_FOLLOW_SYMLINKS = "follow_symlinks=False"


def _warn_ignored(self: Any, method: str, detail: str) -> None:
    """Warn that a pathlib-compat argument is accepted but has no effect.

    Several methods accept arguments for signature compatibility with
    :mod:`pathlib` (``follow_symlinks``, ``case_sensitive``, ``recurse_symlinks``,
    ``buffering``, ``mode``) that fsspec backends cannot honor. Rather than
    silently ignoring a non-default value we warn, so callers relying on the
    behavior find out instead of receiving a wrong result. The message mirrors
    the synchronous :class:`~upath.UPath` wording.
    """
    warnings.warn(
        f"{type(self).__name__}.{method}(): {detail} is currently ignored.",
        UserWarning,
        stacklevel=3,
    )


# --- async I/O mixin -------------------------------------------------------


class _AsyncPathMixin:
    """Async filesystem I/O methods for :class:`AsyncUPath`.

    Mixed in *before* the synchronous implementation class so these async
    methods shadow their blocking counterparts.

    Note: this mixin declares an empty ``__slots__`` so it can be combined with
    the slotted synchronous implementation classes without an instance layout
    conflict. The ``_async_fs_cached`` slot is added by the concrete async
    subclasses (see :func:`_async_class_for` and :class:`AsyncUPath`).
    """

    __slots__ = ()

    # populated on synthesized subclasses; None on the AsyncUPath base
    _sync_class: type[UPath] | None = None

    def _sync_view(self) -> UPath:
        """A synchronous UPath equivalent, used to offload customized sync I/O.

        Reconstructs a sync ``UPath`` (preserving storage options) for backends
        whose I/O methods carry custom logic the generic async layer can't
        replicate. Only used for those offloaded methods.

        The reconstructed path reuses this path's underlying fsspec filesystem
        instance (``self.fs``) rather than resolving a fresh one. For non-cachable
        filesystems (e.g. ftp) this matters: the thread-offload async wrapper
        wraps ``self.fs``, so any cache invalidation an offloaded sync method
        performs must land on that same instance to be visible to later async
        reads.
        """
        sync_cls = self._sync_class or UPath
        sync_path = sync_cls(str(self), **dict(self.storage_options))  # type: ignore[attr-defined]
        sync_path._fs_cached = self.fs  # type: ignore[attr-defined]
        return sync_path

    def __new__(
        cls,
        *args: JoinablePathLike,
        protocol: str | None = None,
        chain_parser: Any = None,
        **storage_options: Any,
    ) -> AsyncUPath:
        # `chain_parser` is consumed by __init__; accept it here so it is not
        # misrouted into storage_options during dispatch.
        if "scheme" in storage_options:
            warnings.warn(
                "use 'protocol' kwarg instead of 'scheme'",
                DeprecationWarning,
                stacklevel=2,
            )
            protocol = storage_options.pop("scheme")

        pth_protocol = get_upath_protocol(
            args[0] if args else "",
            protocol=protocol,
            storage_options=storage_options,
        )
        # subclasses default to their own registered protocol
        if protocol is None and cls._sync_class is not None:
            impl_protocols = _get_implementation_protocols(cls._sync_class)
            if not pth_protocol and impl_protocols:
                pth_protocol = impl_protocols[0]

        async_cls = get_async_upath_class(pth_protocol)
        if async_cls is None:
            raise ValueError(f"Unsupported filesystem: {pth_protocol!r}")
        return object.__new__(async_cls)

    # -- filesystem resolution --------------------------------------------

    @property
    def _async_fs(self) -> AsyncFileSystem:
        """The (cached) async fsspec filesystem backing this path."""
        try:
            return self._async_fs_cached
        except AttributeError:
            # resolve from the chain-aware sync instance so chained URLs
            # (e.g. simplecache::memory://) are handled correctly
            fs = resolve_async_fs(self.fs)  # type: ignore[attr-defined]
            self._async_fs_cached = fs
            return fs

    async def aclose(self) -> None:
        """Release the async filesystem cached on this path.

        Long-running programs can call this (or use ``async with``) to drop the
        resolved async filesystem once a path is done with. Native async backends
        are created with ``skip_instance_cache=True`` (see
        :func:`~upath._async._fs.resolve_async_fs`), so this path holds the only
        strong reference to them; dropping it lets the underlying client/session
        be collected instead of living for the lifetime of the path object. Safe
        to call more than once -- the next I/O call transparently re-resolves the
        filesystem.
        """
        try:
            del self._async_fs_cached
        except AttributeError:
            # never resolved, or already closed -- nothing to release
            pass

    async def __aenter__(self) -> AsyncUPath:
        return self  # type: ignore[return-value]

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    @property
    def info(self) -> AsyncUPathInfo:  # type: ignore[override]
        """Async filesystem info for this path (status checks are coroutines)."""
        return AsyncUPathInfo(self)  # type: ignore[arg-type]

    # -- reading ----------------------------------------------------------

    async def read_bytes(self) -> bytes:
        """Return the whole file contents as bytes."""
        return await self._async_fs._cat_file(self.path)  # type: ignore[attr-defined]

    async def read_text(
        self,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        """Return the whole file decoded as text."""
        data = await self.read_bytes()
        text = data.decode(encoding or "utf-8", errors or "strict")
        if newline is None:
            # universal newlines
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text

    async def open(
        self,
        mode: str = "rb",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        **fsspec_kwargs: Any,
    ) -> Any:
        """Open the file and return an async file object.

        Uses the backend's native ``open_async`` when it provides binary async
        streaming, otherwise offloads a synchronous file handle to a thread.
        Use it as an async context manager::

            async with await path.open("rb") as f:
                data = await f.read()
        """
        if buffering != -1:
            _warn_ignored(self, "open", "buffering")
        fs = self._async_fs
        if "b" in mode and has_working_open_async(fs):
            try:
                return await fs.open_async(self.path, mode, **fsspec_kwargs)  # type: ignore[attr-defined]
            except (NotImplementedError, ValueError):
                pass
        open_kwargs: dict[str, Any] = dict(fsspec_kwargs)
        if encoding is not None:
            open_kwargs["encoding"] = encoding
        if errors is not None:
            open_kwargs["errors"] = errors
        if newline is not None:
            open_kwargs["newline"] = newline
        executor = executor_for(self.fs)  # type: ignore[attr-defined]
        f = await run_in_thread(
            self.fs.open,  # type: ignore[attr-defined]
            self.path,
            mode,
            executor=executor,
            **open_kwargs,
        )
        return _AsyncFileWrapper(f, executor)

    async def iterdir(self) -> AsyncIterator[AsyncUPath]:
        """Yield async path objects of the directory contents."""
        sep = self.parser.sep  # type: ignore[attr-defined]
        base = self
        if self.parts[-1:] == ("",):  # type: ignore[attr-defined]
            base = self.parent  # type: ignore[attr-defined]
        fs = base._async_fs
        base_path = base.path
        if not await fs._isdir(base_path):  # type: ignore[attr-defined]
            raise NotADirectoryError(str(self))
        for entry in await fs._ls(base_path, detail=True):  # type: ignore[attr-defined]
            name = entry.get("name") if isinstance(entry, dict) else entry
            if name in {".", ".."}:
                continue
            _, _, short = name.removesuffix(sep).rpartition(sep)
            yield base.with_segments(base_path, short)  # type: ignore[attr-defined]

    async def glob(
        self,
        pattern: str,
        *,
        case_sensitive: bool | None = None,
        recurse_symlinks: bool = False,
    ) -> AsyncIterator[AsyncUPath]:
        """Yield paths matching the given relative pattern."""
        if case_sensitive is not None:
            _warn_ignored(self, "glob", "case_sensitive")
        if recurse_symlinks:
            _warn_ignored(self, "glob", "recurse_symlinks=True")
        this = self
        if this._relative_base is not None:  # type: ignore[attr-defined]
            this = this.absolute()  # type: ignore[attr-defined]
        path_pattern = this.joinpath(pattern).path  # type: ignore[attr-defined]
        sep = this.parser.sep  # type: ignore[attr-defined]
        base = this.path
        for name in await this._async_fs._glob(path_pattern):  # type: ignore[attr-defined]
            name = name.removeprefix(base).removeprefix(sep)
            yield this.joinpath(name)  # type: ignore[attr-defined]

    async def rglob(
        self,
        pattern: str,
        *,
        case_sensitive: bool | None = None,
        recurse_symlinks: bool = False,
    ) -> AsyncIterator[AsyncUPath]:
        """Recursively yield paths matching the given relative pattern."""
        if case_sensitive is not None:
            _warn_ignored(self, "rglob", "case_sensitive")
        if recurse_symlinks:
            _warn_ignored(self, "rglob", "recurse_symlinks=True")
        this = self
        if this._relative_base is not None:  # type: ignore[attr-defined]
            this = this.absolute()  # type: ignore[attr-defined]
        r_pattern = this.joinpath("**", pattern).path  # type: ignore[attr-defined]
        sep = this.parser.sep  # type: ignore[attr-defined]
        base = this.path
        for name in await this._async_fs._glob(r_pattern):  # type: ignore[attr-defined]
            name = name.removeprefix(base).removeprefix(sep)
            yield this.joinpath(name)  # type: ignore[attr-defined]

    async def walk(
        self,
        top_down: bool = True,
        on_error: Callable[[OSError], None] | None = None,
        follow_symlinks: bool = False,
    ) -> AsyncIterator[tuple[AsyncUPath, list[str], list[str]]]:
        """Walk the directory tree, yielding ``(dirpath, dirnames, filenames)``."""
        if follow_symlinks:
            _warn_ignored(self, "walk", "follow_symlinks=True")
        fs = self._async_fs
        sep = self.parser.sep  # type: ignore[attr-defined]
        stack: list[Any] = [self]
        while stack:
            path = stack.pop()
            if isinstance(path, tuple):
                yield path
                continue
            try:
                entries = await fs._ls(path.path, detail=True)  # type: ignore[attr-defined]
            except OSError as error:
                if on_error is not None:
                    on_error(error)
                continue
            except NotImplementedError:
                # backend cannot list this path (e.g. a non-directory "root"
                # such as data:); like os.walk on a file, yield nothing for it
                continue
            dirnames: list[str] = []
            filenames: list[str] = []
            for entry in entries:
                name = entry.get("name") if isinstance(entry, dict) else entry
                etype = entry.get("type") if isinstance(entry, dict) else None
                _, _, short = name.removesuffix(sep).rpartition(sep)
                if short in {"", ".", ".."}:
                    continue
                if etype == "directory":
                    dirnames.append(short)
                else:
                    filenames.append(short)
            if top_down:
                yield path, dirnames, filenames
            else:
                stack.append((path, dirnames, filenames))
            for dirname in reversed(dirnames):
                stack.append(path.joinpath(dirname))

    # -- status -----------------------------------------------------------

    async def stat(self, *, follow_symlinks: bool = True) -> UPathStatResult:
        """Return an ``os.stat_result``-like object for this path."""
        if not follow_symlinks:
            _warn_ignored(self, "stat", _IGNORED_FOLLOW_SYMLINKS)
        info = await self._async_fs._info(self.path)  # type: ignore[attr-defined]
        return UPathStatResult.from_info(info)

    async def lstat(self) -> UPathStatResult:
        return await self.stat(follow_symlinks=False)

    async def samefile(self, other_path: Any) -> bool:
        """Whether this path and ``other_path`` point to the same file."""
        st = await self.stat()
        if isinstance(other_path, _AsyncPathMixin):
            other_st = await other_path.stat()
        else:
            other_st = await self.with_segments(other_path).stat()  # type: ignore[attr-defined]
        return st == other_st

    async def exists(self, *, follow_symlinks: bool = True) -> bool:
        """Whether this path exists."""
        if not follow_symlinks:
            _warn_ignored(self, "exists", _IGNORED_FOLLOW_SYMLINKS)
        return await self._async_fs._exists(self.path)  # type: ignore[attr-defined]

    async def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        """Whether this path is a directory."""
        if not follow_symlinks:
            _warn_ignored(self, "is_dir", _IGNORED_FOLLOW_SYMLINKS)
        return await self._async_fs._isdir(self.path)  # type: ignore[attr-defined]

    async def is_file(self, *, follow_symlinks: bool = True) -> bool:
        """Whether this path is a regular file."""
        if not follow_symlinks:
            _warn_ignored(self, "is_file", _IGNORED_FOLLOW_SYMLINKS)
        return await self._async_fs._isfile(self.path)  # type: ignore[attr-defined]

    # -- writing / mutation ----------------------------------------------

    async def write_bytes(self, data: Any) -> int:
        """Write bytes to this path, replacing any existing content."""
        view = memoryview(data)
        await self._async_fs._pipe_file(self.path, view.tobytes())  # type: ignore[attr-defined]
        return view.nbytes

    async def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        """Write text to this path, replacing any existing content."""
        if not isinstance(data, str):
            raise TypeError(f"data must be str, not {type(data).__name__}")
        if newline is not None:
            data = data.replace("\n", newline)
        encoded = data.encode(encoding or "utf-8", errors or "strict")
        await self.write_bytes(encoded)
        return len(data)

    async def mkdir(
        self,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        """Create a new directory at this path."""
        if mode != 0o777:
            _warn_ignored(self, "mkdir", "mode")
        fs = self._async_fs
        if parents and not exist_ok and await self.exists():
            raise FileExistsError(str(self))
        try:
            if parents:
                await fs._makedirs(self.path, exist_ok=exist_ok)  # type: ignore[attr-defined]
            else:
                await fs._mkdir(self.path, create_parents=parents)  # type: ignore[attr-defined]
        except FileExistsError:
            if not exist_ok:
                raise FileExistsError(str(self))
            if not await self.is_dir():
                raise FileExistsError(str(self))

    async def touch(self, mode: int = 0o666, exist_ok: bool = True) -> None:
        """Create this file (or update mtime) if it doesn't exist."""
        if mode != 0o666:
            _warn_ignored(self, "touch", "mode")
        exists = await self.exists()
        if exists and not exist_ok:
            raise FileExistsError(str(self))
        executor = executor_for(self.fs)  # type: ignore[attr-defined]
        if not exists:
            await run_in_thread(self.fs.touch, self.path, truncate=True, executor=executor)  # type: ignore[attr-defined]
        else:
            try:
                await run_in_thread(self.fs.touch, self.path, truncate=False, executor=executor)  # type: ignore[attr-defined]
            except (NotImplementedError, ValueError):
                pass

    async def unlink(self, missing_ok: bool = False) -> None:
        """Remove this file."""
        if not await self.exists():
            if not missing_ok:
                raise FileNotFoundError(str(self))
            return
        await self._async_fs._rm(self.path, recursive=False)  # type: ignore[attr-defined]

    async def rmdir(self, recursive: bool = True) -> None:
        """Remove this directory (recursively by default; non-standard)."""
        if not await self.is_dir():
            raise NotADirectoryError(str(self))
        if not recursive:
            async for _ in self.iterdir():
                raise OSError(f"Not recursive and directory not empty: {self}")
        await self._async_fs._rm(self.path, recursive=recursive)  # type: ignore[attr-defined]

    async def rename(
        self,
        target: JoinablePathLike,
        *,
        recursive: Any = UNSET_DEFAULT,
        maxdepth: int | None = UNSET_DEFAULT,
        **kwargs: Any,
    ) -> AsyncUPath:
        """Rename this file or directory to the given target.

        The target-normalization mirrors :meth:`upath.UPath.rename`; only the
        terminal filesystem move is performed asynchronously.
        """
        # check protocol compatibility
        target_protocol = get_upath_protocol(target)
        if target_protocol and target_protocol != self.protocol:  # type: ignore[attr-defined]
            raise ValueError(
                f"expected protocol {self.protocol!r}, got: {target_protocol!r}"  # type: ignore[attr-defined]
            )
        # ensure target is an absolute AsyncUPath (path algebra is synchronous)
        if not isinstance(target, type(self)):
            if isinstance(target, (UPath, PurePath)):
                target_str = target.as_posix()
            else:
                target_str = str(target)
            if target_protocol:
                target = self.with_segments(target_str)  # type: ignore[attr-defined]
            elif self.anchor and target_str.startswith(self.anchor):  # type: ignore[attr-defined]
                target = self.with_segments(target_str)  # type: ignore[attr-defined]
            elif not self.anchor and target_str.startswith("./"):  # type: ignore[attr-defined]
                target = (
                    self.cwd()  # type: ignore[attr-defined]
                    .joinpath(target_str.removeprefix("./"))
                    .relative_to(self.cwd())  # type: ignore[attr-defined]
                )
            else:
                target = self.cwd().joinpath(target_str).relative_to(self.cwd())  # type: ignore[attr-defined]
        if target == self:
            return target  # type: ignore[return-value]
        source_abs = self.absolute()  # type: ignore[attr-defined]
        target_abs = target.absolute()
        if ".." in target_abs.parts or "." in target_abs.parts:
            target_abs = target_abs.resolve()
        if recursive is not UNSET_DEFAULT:
            kwargs["recursive"] = recursive
        if maxdepth is not UNSET_DEFAULT:
            kwargs["maxdepth"] = maxdepth
        await run_in_thread(  # type: ignore[attr-defined]
            self.fs.mv,
            source_abs.path,
            target_abs.path,
            executor=executor_for(self.fs),
            **kwargs,
        )
        # invalidate listing caches so subsequent async reads observe the move
        # (some filesystems, e.g. ftp, don't self-invalidate on mv). The async
        # wrapper wraps self.fs, so invalidating it here is what those reads see.
        self._invalidate_cache(source_abs.parent.path, target_abs.parent.path)
        return target  # type: ignore[return-value]

    async def replace(self, target: JoinablePathLike) -> AsyncUPath:
        return await self.rename(target)

    def _invalidate_cache(self, *paths: str) -> None:
        invalidate = getattr(self.fs, "invalidate_cache", None)  # type: ignore[attr-defined]
        if invalidate is None:
            return
        for path in dict.fromkeys(paths):
            try:
                invalidate(path)
            except Exception:  # pragma: no cover - defensive; cache is best-effort
                pass

    # -- copy / move ------------------------------------------------------

    async def copy(self, target: Any, **kwargs: Any) -> AsyncUPath:
        """Recursively copy this file or directory tree to ``target``."""
        target_upath = self._resolve_target(target)
        if await target_upath.is_dir():
            raise IsADirectoryError(str(target_upath))
        await self._acopy_tree(self, target_upath, **kwargs)
        return target_upath

    async def copy_into(self, target_dir: Any, **kwargs: Any) -> AsyncUPath:
        """Copy this file or directory tree into the existing directory."""
        target_dir_upath = self._resolve_target(target_dir)
        if not await target_dir_upath.exists():
            raise FileNotFoundError(str(target_dir_upath))
        if not await target_dir_upath.is_dir():
            raise NotADirectoryError(str(target_dir_upath))
        name = self.name  # type: ignore[attr-defined]
        if not name:
            raise ValueError(f"{self!r} has an empty name")
        return await self.copy(target_dir_upath.joinpath(name), **kwargs)

    async def move(self, target: Any, **kwargs: Any) -> AsyncUPath:
        """Recursively move this file or directory tree to ``target``."""
        result = await self.copy(target, **kwargs)
        await self._async_fs._rm(  # type: ignore[attr-defined]
            self.path, recursive=await self.is_dir()
        )
        return result

    async def move_into(self, target_dir: Any, **kwargs: Any) -> AsyncUPath:
        """Move this file or directory tree into the existing directory."""
        name = self.name  # type: ignore[attr-defined]
        if not name:
            raise ValueError(f"{self!r} has an empty name")
        target_dir_upath = self._resolve_target(target_dir)
        parent = target_dir_upath
        if not await parent.exists():
            raise FileNotFoundError(str(parent))
        if not await parent.is_dir():
            raise NotADirectoryError(str(parent))
        return await self.move(target_dir_upath.joinpath(name), **kwargs)

    async def _acopy_tree(
        self,
        source: AsyncUPath,
        dest: AsyncUPath,
        **kwargs: Any,
    ) -> None:
        """Recursively copy ``source`` to ``dest`` (cross-filesystem safe)."""
        if await source.is_dir():
            await dest.mkdir(parents=True, exist_ok=True)
            async for child in source.iterdir():
                await self._acopy_tree(child, dest.joinpath(child.name), **kwargs)
        else:
            data = await source.read_bytes()
            await dest.write_bytes(data)

    # -- helpers ----------------------------------------------------------

    def _resolve_target(self, target: Any) -> AsyncUPath:
        """Normalize a copy/move target to an AsyncUPath (path algebra only)."""
        if isinstance(target, _AsyncPathMixin):
            return target  # type: ignore[return-value]
        if isinstance(target, str):
            proto = get_upath_protocol(target)
            if proto != self.protocol:  # type: ignore[attr-defined]
                return AsyncUPath(target)
            return self.with_segments(target)  # type: ignore[attr-defined]
        if isinstance(target, (UPath, PurePath)):
            return AsyncUPath(target.as_posix())
        return AsyncUPath(target)


class AsyncUPath(_AsyncPathMixin, UPath):
    """Async, fsspec-backed pathlib-style path.

    Construct exactly like :class:`upath.UPath`; filesystem I/O methods are
    coroutines / async iterators::

        p = AsyncUPath("memory://bucket/key.txt")
        await p.write_bytes(b"data")
        assert await p.read_bytes() == b"data"
        async for child in p.parent.iterdir():
            print(child)
    """

    __slots__ = ("_async_fs_cached",)
