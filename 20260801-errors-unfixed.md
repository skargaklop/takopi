Error in sys.excepthook:
Traceback (most recent call last):
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\main.py", line 86, in except_hook
    console_stderr.print(rich_tb)
    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\rich\console.py", line 1731, in print
    extend(render(renderable, render_options))
    ~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\rich\console.py", line 1339, in render
    for render_output in iter_render:
                         ^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\rich\traceback.py", line 726, in __rich_console__
    yield render_stack(stack, last)
          ~~~~~~~~~~~~^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\rich\console.py", line 498, in _replace
    return Group(*renderables, fit=fit)
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\rich\traceback.py", line 661, in render_stack
    self._render_stack(stack),
    ~~~~~~~~~~~~~~~~~~^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\rich\console.py", line 498, in _replace
    return Group(*renderables, fit=fit)
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\rich\traceback.py", line 835, in _render_stack
    code_lines = linecache.getlines(frame.filename)
  File "C:\Users\DELL E5570\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\Lib\linecache.py", line 42, in getlines
    return updatecache(filename, module_globals)
  File "C:\Users\DELL E5570\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\Lib\linecache.py", line 191, in updatecache
    with tokenize.open(fullname) as fp:
         ~~~~~~~~~~~~~^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\Lib\tokenize.py", line 461, in open
    buffer = _builtin_open(filename, 'rb')
KeyboardInterrupt

Original exception was:
Traceback (most recent call last):
  File "D:\Projects\takopi\src\takopi\telegram\loop.py", line 1520, in run_main_loop
    async with anyio.create_task_group() as tg:
               ~~~~~~~~~~~~~~~~~~~~~~~^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\anyio\_backends\_asyncio.py", line 819, in __aexit__
    raise exc_val
  File "D:\Projects\takopi\src\takopi\telegram\loop.py", line 2581, in run_main_loop
    async for update in poller_fn(cfg):
        await route_update(update)
  File "D:\Projects\takopi\src\takopi\telegram\loop.py", line 478, in poll_updates
    async for msg in poll_incoming(
    ...<5 lines>...
        yield msg
  File "D:\Projects\takopi\src\takopi\telegram\parsing.py", line 227, in poll_incoming
    updates = await bot.get_updates(
              ^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
    )
    ^
  File "D:\Projects\takopi\src\takopi\telegram\client.py", line 153, in get_updates
    return await self._call_with_retry_after(execute)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\Projects\takopi\src\takopi\telegram\client.py", line 136, in _call_with_retry_after
    return await fn()
           ^^^^^^^^^^
  File "D:\Projects\takopi\src\takopi\telegram\client.py", line 147, in execute
    return await self._client.get_updates(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
    )
    ^
  File "D:\Projects\takopi\src\takopi\telegram\client_api.py", line 369, in get_updates
    result = await self._post("getUpdates", params)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\Projects\takopi\src\takopi\telegram\client_api.py", line 348, in _post
    return await self._request(method, json=json_data)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\Projects\takopi\src\takopi\telegram\client_api.py", line 235, in _request
    resp = await self._http_client.post(f"{self._base}/{method}", json=json)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpx\_client.py", line 1859, in post
    return await self.request(
           ^^^^^^^^^^^^^^^^^^^
    ...<13 lines>...
    )
    ^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpx\_client.py", line 1540, in request
    return await self.send(request, auth=auth, follow_redirects=follow_redirects)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpx\_client.py", line 1629, in send
    response = await self._send_handling_auth(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<4 lines>...
    )
    ^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpx\_client.py", line 1657, in _send_handling_auth
    response = await self._send_handling_redirects(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
    )
    ^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpx\_client.py", line 1694, in _send_handling_redirects
    response = await self._send_single_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpx\_client.py", line 1730, in _send_single_request
    response = await transport.handle_async_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpx\_transports\default.py", line 394, in handle_async_request
    resp = await self._pool.handle_async_request(req)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpcore\_async\connection_pool.py", line 256, in handle_async_request
    raise exc from None
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpcore\_async\connection_pool.py", line 236, in handle_async_request
    response = await connection.handle_async_request(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        pool_request.request
        ^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpcore\_async\connection.py", line 103, in handle_async_request
    return await self._connection.handle_async_request(request)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpcore\_async\http11.py", line 136, in handle_async_request
    raise exc
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpcore\_async\http11.py", line 106, in handle_async_request
    ) = await self._receive_response_headers(**kwargs)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpcore\_async\http11.py", line 177, in _receive_response_headers
    event = await self._receive_event(timeout=timeout)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpcore\_async\http11.py", line 217, in _receive_event
    data = await self._network_stream.read(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        self.READ_NUM_BYTES, timeout=timeout
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\httpcore\_backends\anyio.py", line 35, in read
    return await self._stream.receive(max_bytes=max_bytes)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\anyio\streams\tls.py", line 254, in receive
    data = await self._call_sslobject_method(self._ssl_object.read, max_bytes)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\anyio\streams\tls.py", line 194, in _call_sslobject_method
    data = await self.transport_stream.receive()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\anyio\_backends\_asyncio.py", line 1337, in receive
    await self._protocol.read_event.wait()
  File "C:\Users\DELL E5570\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\Lib\asyncio\locks.py", line 213, in wait
    await fut
asyncio.exceptions.CancelledError

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "C:\Users\DELL E5570\.local\bin\takopi.exe\__main__.py", line 10, in <module>
    sys.exit(main())
             ~~~~^^
  File "D:\Projects\takopi\src\takopi\cli\__init__.py", line 185, in main
    app()
    ~~~^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\main.py", line 1154, in __call__
    raise e
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\main.py", line 1137, in __call__
    return get_command(self)(*args, **kwargs)
           ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\_click\core.py", line 807, in __call__
    return self.main(*args, **kwargs)
           ~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\core.py", line 1203, in main
    return _main(
        self,
    ...<6 lines>...
        **extra,
    )
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\core.py", line 189, in _main
    rv = self.invoke(ctx)
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\core.py", line 1106, in invoke
    rv = super().invoke(ctx)
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\_click\core.py", line 746, in invoke
    return ctx.invoke(self.callback, **ctx.params)
           ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\_click\core.py", line 489, in invoke
    return callback(*args, **kwargs)
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\typer\main.py", line 1524, in wrapper
    return callback(**use_params)
  File "D:\Projects\takopi\src\takopi\cli\run.py", line 383, in app_main
    run_auto_router(
    ~~~~~~~~~~~~~~~^
        default_engine_override=None,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
        onboard=onboard,
        ^^^^^^^^^^^^^^^^
    )
    ^
  File "D:\Projects\takopi\src\takopi\cli\run.py", line 319, in _run_auto_router
    transport_backend.build_and_run(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        final_notify=final_notify,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
        runtime=runtime,
        ^^^^^^^^^^^^^^^^
    )
    ^
  File "D:\Projects\takopi\src\takopi\telegram\backend.py", line 165, in build_and_run
    anyio.run(run_loop)
    ~~~~~~~~~^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\anyio\_core\_eventloop.py", line 83, in run
    return async_backend.run(func, args, {}, backend_options)
           ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\anyio\_backends\_asyncio.py", line 2481, in run
    return runner.run(wrapper())
           ~~~~~~~~~~^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\Lib\asyncio\runners.py", line 127, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\Lib\asyncio\base_events.py", line 719, in run_until_complete
    return future.result()
           ~~~~~~~~~~~~~^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\anyio\_backends\_asyncio.py", line 2464, in wrapper
    return await func(*args)
           ^^^^^^^^^^^^^^^^^
  File "D:\Projects\takopi\src\takopi\telegram\backend.py", line 157, in run_loop
    await run_main_loop(
    ...<5 lines>...
    )
  File "D:\Projects\takopi\src\takopi\telegram\bridge.py", line 452, in run_main_loop
    await _run_main_loop(
    ...<5 lines>...
    )
  File "D:\Projects\takopi\src\takopi\telegram\loop.py", line 2585, in run_main_loop
    await cfg.exec_cfg.transport.close()
  File "D:\Projects\takopi\src\takopi\telegram\bridge.py", line 201, in close
    await self._bot.close()
  File "D:\Projects\takopi\src\takopi\telegram\client.py", line 127, in close
    await self._outbox.close()
  File "D:\Projects\takopi\src\takopi\telegram\outbox.py", line 94, in close
    await self._tg.__aexit__(None, None, None)
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\anyio\_backends\_asyncio.py", line 826, in __aexit__
    return self.cancel_scope.__exit__(exc_type, exc_val, exc_tb)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\DELL E5570\AppData\Roaming\uv\tools\takopi\Lib\site-packages\anyio\_backends\_asyncio.py", line 472, in __exit__
    raise RuntimeError(
    ...<2 lines>...
    )
RuntimeError: Attempted to exit a cancel scope that isn't the current tasks's current cancel scope
=====================================
2026-08-01T19:51:20.092349Z [info     ] subprocess.spawn               [takopi.runners.agy] args=['--dangerously-skip-permissions', '--conversation', '834d39a7-838f-4c73-a8c3-2a710cc483b4', '-p', 'What author recommends to read additionally to article?\n\n[Takopi file delivery]\nTo send a file to the user via Takopi (not Telegram agent tools):\n1. Write the file under the project root.\n2. Include a line exactly like:\n   [[takopi-send: /absolute/path/to/file.ext]]\nAllowed extensions: .jpg, .png, .gif, .pdf, .md, .html, .doc, .docx, .xls, .xlsx\nPaths must resolve inside the project (absolute or relative).'] branch=None chat_id=-1003932376071 cmd='C:\\Users\\DELL E5570\\AppData\\Local\\agy\\bin\\agy.exe' cwd=D:\Projects engine=agy pid=21352 project=projects resume=834d39a7-838f-4c73-a8c3-2a710cc483b4 user_msg_id=2459
2026-08-01T19:56:24.285038Z [info     ] subprocess.exit                [takopi.runners.agy] branch=None chat_id=-1003932376071 cwd=D:\Projects engine=agy pid=21352 project=projects rc=1 resume=834d39a7-838f-4c73-a8c3-2a710cc483b4 user_msg_id=2459
2026-08-01T19:56:24.286324Z [info     ] runner.completed               [takopi.runner_bridge] action_count=0 answer_len=55 branch=None chat_id=-1003932376071 cwd=D:\Projects elapsed_s=306.81 engine=agy error='agy failed (rc=1).' ok=False project=projects resume=834d39a7-838f-4c73-a8c3-2a710cc483b4 user_msg_id=2459
2026-08-01T19:57:32.007835Z [info     ] handle.incoming                [takopi.runner_bridge] branch=None channel_id=-1003932376071 chat_id=-1003932376071 cwd=D:\Projects engine=agy project=projects resume=834d39a7-838f-4c73-a8c3-2a710cc483b4 text='What author recommends to read additionally to article?\n\n[Takopi file delivery]\nTo send a file to the user via Takopi (not Telegram agent tools):\n1. Write the file under the project root.\n2. Include a line exactly like:\n   [[takopi-send: /absolute/path/to/file.ext]]\nAllowed extensions: .jpg, .png, .gif, .pdf, .md, .html, .doc, .docx, .xls, .xlsx\nPaths must resolve inside the project (absolute or relative).' user_msg_id=2462
2026-08-01T19:57:34.610756Z [info     ] runner.start                   [takopi.runners.agy] branch=None chat_id=-1003932376071 cwd=D:\Projects engine=agy project=projects prompt='What author recommends to read additionally to article?\n\n[Takopi file delivery]\nTo send a file to the user via Takopi (not Telegram agent tools):\n1. Write the file under the project root.\n2. Include a line exactly like:\n   [[takopi-send: /absolute/path/to/file.ext]]\nAllowed extensions: .jpg, .png, .gif, .pdf, .md, .html, .doc, .docx, .xls, .xlsx\nPaths must resolve inside the project (absolute or relative).' prompt_len=409 resume=834d39a7-838f-4c73-a8c3-2a710cc483b4 user_msg_id=2462
2026-08-01T19:57:34.617685Z [info     ] subprocess.spawn               [takopi.runners.agy] args=['--dangerously-skip-permissions', '--conversation', '834d39a7-838f-4c73-a8c3-2a710cc483b4', '-p', 'What author recommends to read additionally to article?\n\n[Takopi file delivery]\nTo send a file to the user via Takopi (not Telegram agent tools):\n1. Write the file under the project root.\n2. Include a line exactly like:\n   [[takopi-send: /absolute/path/to/file.ext]]\nAllowed extensions: .jpg, .png, .gif, .pdf, .md, .html, .doc, .docx, .xls, .xlsx\nPaths must resolve inside the project (absolute or relative).'] branch=None chat_id=-1003932376071 cmd='C:\\Users\\DELL E5570\\AppData\\Local\\agy\\bin\\agy.exe' cwd=D:\Projects engine=agy pid=19756 project=projects resume=834d39a7-838f-4c73-a8c3-2a710cc483b4 user_msg_id=2462
2026-08-01T19:57:38.949991Z [info     ] subprocess.exit                [takopi.runners.agy] branch=None chat_id=-1003932376071 cwd=D:\Projects engine=agy pid=19756 project=projects rc=1 resume=834d39a7-838f-4c73-a8c3-2a710cc483b4 user_msg_id=2462
2026-08-01T19:57:38.952332Z [info     ] runner.completed               [takopi.runner_bridge] action_count=0 answer_len=109 branch=None chat_id=-1003932376071 cwd=D:\Projects elapsed_s=6.94 engine=agy error='agy failed (rc=1).' ok=False project=projects resume=834d39a7-838f-4c73-a8c3-2a710cc483b4 user_msg_id=2462
