interface sync_iface#(parameter SYNC_BARRIER_WIDTH=8)();
    wire[SYNC_BARRIER_WIDTH-1:0] barrier;
    wire enable;
    wire ready;

    modport proc(input ready, output enable, barrier);
    modport sync(output ready, input enable, barrier);

endinterface
